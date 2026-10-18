package com.rami.devicewatch;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Dashboard: one card per laptop with live status and power buttons. */
public class MainActivity extends Activity {
    /** A device with no heartbeat for this long is shown as offline (> 2x agent heartbeat). */
    static final long STALE_SEC = 35 * 60;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Map<String, JSONObject> devices = new TreeMap<>();
    private Prefs prefs;
    private String lastId, signature;
    private long fastUntil;
    private boolean visible;
    private LinearLayout list;
    private TextView updated;

    private final Runnable pollTask = this::poll;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = new Prefs(this);

        LinearLayout root = Ui.column(this);
        int pad = Ui.dp(this, 16);
        root.setPadding(pad, pad, pad, pad);

        // header
        LinearLayout header = Ui.row(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout titles = Ui.column(this);
        titles.addView(Ui.text(this, "DeviceWatch", 24, Ui.TEXT, true));
        updated = Ui.text(this, "Connecting…", 13, Ui.DIM, false);
        titles.addView(updated);
        header.addView(titles, new LinearLayout.LayoutParams(0, -2, 1f));
        Button refresh = Ui.button(this, "↻", false);
        refresh.setTextSize(18);
        refresh.setOnClickListener(v -> sendCommand("status", "*"));
        Button settings = Ui.button(this, "⚙", false);
        settings.setTextSize(18);
        settings.setOnClickListener(v -> startActivity(new Intent(this, SettingsActivity.class)));
        int sq = Ui.dp(this, 46);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(sq, sq);
        lp.leftMargin = Ui.dp(this, 8);
        header.addView(refresh, lp);
        header.addView(settings, new LinearLayout.LayoutParams(lp));
        root.addView(header);

        ScrollView scroll = new ScrollView(this);
        list = Ui.column(this);
        list.setPadding(0, Ui.dp(this, 14), 0, Ui.dp(this, 24));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));
        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        if (!prefs.configured()) {
            startActivity(new Intent(this, SettingsActivity.class));
            return;
        }
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        WatchService.sync(this);
        if (!prefs.signature().equals(signature)) {      // settings changed: start fresh
            signature = prefs.signature();
            devices.clear();
            lastId = null;
        }
        sendCommand("status", "*");
        poll();
    }

    @Override
    protected void onPause() {
        super.onPause();
        visible = false;
        ui.removeCallbacks(pollTask);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        io.shutdownNow();
    }

    // ------------------------------------------------------------------ network
    private void sendCommand(String cmd, String to) {
        io.execute(() -> {
            try {
                Api.command(prefs, cmd, to, "app");
                ui.post(() -> {
                    if (!cmd.equals("status")) toast("Sent “" + cmd + "” to " + (to.equals("*") ? "all" : to));
                    fastUntil = System.currentTimeMillis() + 25000;
                    schedule(1500);
                });
            } catch (Exception e) {
                ui.post(() -> toast("Couldn't reach the server"));
            }
        });
    }

    private void poll() {
        ui.removeCallbacks(pollTask);
        final String since = lastId != null ? lastId : (STALE_SEC * 2 / 60) + "m";
        final String url = prefs.server() + "/" + prefs.topic() + "-hb/json?poll=1&since=" + since;
        final String token = prefs.token();
        io.execute(() -> {
            String body = null;
            try {
                body = Api.get(url, token);
            } catch (Exception ignored) {
            }
            final String result = body;
            ui.post(() -> {
                if (result == null) {
                    updated.setText("Offline - retrying…");
                } else {
                    ingest(result);
                    updated.setText("Updated " + DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date()));
                }
                render();
                schedule(System.currentTimeMillis() < fastUntil ? 3000 : 30000);
            });
        });
    }

    private void schedule(long ms) {
        ui.removeCallbacks(pollTask);
        if (visible) ui.postDelayed(pollTask, ms);
    }

    private void ingest(String ndjson) {
        for (String line : ndjson.split("\n")) {
            if (line.isEmpty()) continue;
            try {
                JSONObject ev = new JSONObject(line);
                if (!"message".equals(ev.optString("event"))) continue;
                lastId = ev.optString("id", lastId);
                JSONObject hb = new JSONObject(ev.optString("message"));
                String name = hb.optString("d");
                if (name.isEmpty() || "dryrun".equals(hb.optString("type"))) continue;
                hb.put("_t", ev.optLong("time"));
                devices.put(name, hb);
            } catch (Exception ignored) {
            }
        }
    }

    // ------------------------------------------------------------------ UI
    private void render() {
        list.removeAllViews();
        if (devices.isEmpty()) {
            TextView empty = Ui.text(this, "No devices yet.\nMake sure the agents are running and use the same topic.",
                    15, Ui.DIM, false);
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, Ui.dp(this, 40), 0, 0);
            list.addView(empty);
            return;
        }
        long now = System.currentTimeMillis() / 1000;
        for (Map.Entry<String, JSONObject> e : devices.entrySet()) {
            list.addView(card(e.getKey(), e.getValue(), now), Ui.fullWidth(this, 0));
            View gap = new View(this);
            list.addView(gap, new LinearLayout.LayoutParams(1, Ui.dp(this, 14)));
        }
    }

    private View card(String name, JSONObject hb, long now) {
        long age = now - hb.optLong("_t");
        String s = hb.optString("s", "up");
        int color;
        String label;
        if ("sleep".equals(s)) { color = Ui.AMBER; label = "● Sleeping"; }
        else if ("off".equals(s)) { color = Ui.RED; label = "● Turned off"; }
        else if (age > STALE_SEC) { color = Ui.RED; label = "● Offline"; }
        else { color = Ui.GREEN; label = "● Online"; }
        boolean live = color == Ui.GREEN;

        LinearLayout card = Ui.column(this);
        int p = Ui.dp(this, 16);
        card.setPadding(p, p, p, p);
        card.setBackground(Ui.round(this, Ui.CARD, Ui.LINE, 18));

        LinearLayout top = Ui.row(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView icon = Ui.text(this, hb.optString("e", "💻"), 30, Ui.TEXT, false);
        icon.setPadding(0, 0, Ui.dp(this, 12), 0);
        top.addView(icon);
        LinearLayout names = Ui.column(this);
        names.addView(Ui.text(this, name, 17, Ui.TEXT, true));
        names.addView(Ui.text(this, label, 13, color, false));
        top.addView(names);
        card.addView(top);

        String activity;
        if (!live) activity = "—";
        else if (!hb.optString("app").isEmpty()) activity = "🎮 " + hb.optString("app");
        else if (!hb.optString("fg").isEmpty()) activity = "In front: " + hb.optString("fg");
        else activity = "No tracked app open";
        TextView act = Ui.text(this, activity, 16, Ui.TEXT, false);
        act.setPadding(0, Ui.dp(this, 14), 0, Ui.dp(this, 4));
        card.addView(act);

        StringBuilder meta = new StringBuilder();
        if (!hb.isNull("bat") && hb.has("bat"))
            meta.append("🔋 ").append(hb.optInt("bat")).append('%').append(hb.optBoolean("chg") ? " ⚡" : "").append("   ");
        if (live && hb.optLong("idle") >= 60) meta.append("💤 idle ").append(Ui.duration(hb.optLong("idle"))).append("   ");
        if (live && hb.optLong("up") > 0) meta.append("⏱ up ").append(Ui.duration(hb.optLong("up"))).append("   ");
        meta.append("seen ").append(Ui.ago(age));
        card.addView(Ui.text(this, meta.toString(), 13, Ui.DIM, false));

        LinearLayout row1 = Ui.row(this);
        row1.setPadding(0, Ui.dp(this, 14), 0, 0);
        row1.addView(action(name, "lock", "🔒\nLock", false), Ui.weight(this, 4));
        row1.addView(action(name, "sleep", "😴\nSleep", false), Ui.weight(this, 4));
        row1.addView(action(name, "restart", "🔄\nRestart", false), Ui.weight(this, 4));
        row1.addView(action(name, "shutdown", "⏻\nOff", true), Ui.weight(this, 4));
        card.addView(row1);

        LinearLayout row2 = Ui.row(this);
        row2.setPadding(0, Ui.dp(this, 8), 0, 0);
        row2.addView(action(name, "status", "📊 Status", false), Ui.weight(this, 4));
        row2.addView(action(name, "cancel", "✋ Cancel pending", false), Ui.weight(this, 4));
        card.addView(row2);
        return card;
    }

    private Button action(String device, String cmd, String label, boolean danger) {
        Button b = Ui.button(this, label, danger);
        b.setOnClickListener(v -> {
            if (cmd.equals("sleep") || cmd.equals("restart") || cmd.equals("shutdown")) {
                String verb = cmd.equals("shutdown") ? "Shut down" : cmd.substring(0, 1).toUpperCase() + cmd.substring(1);
                new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                        .setTitle(verb + " " + device + "?")
                        .setMessage("It happens after a short countdown. You can still cancel.")
                        .setPositiveButton(verb, (d, w) -> sendCommand(cmd, device))
                        .setNegativeButton("No", null)
                        .show();
            } else {
                sendCommand(cmd, device);
            }
        });
        return b;
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
