package com.rami.devicewatch;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Dashboard: one card per laptop, plus "Select" mode to control several at once. */
public class MainActivity extends Activity implements Hub.Listener {
    private Hub hub;
    private LinearLayout list, bulkBar;
    private TextView updated, bulkLabel;
    private Button selectBtn;
    private boolean selecting;
    private final Set<String> selected = new LinkedHashSet<>();

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        hub = Hub.get(this);

        LinearLayout root = Ui.column(this);
        int pad = Ui.dp(this, 16);
        root.setPadding(pad, pad, pad, 0);

        LinearLayout header = Ui.row(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout titles = Ui.column(this);
        titles.addView(Ui.text(this, "DeviceWatch", 24, Ui.TEXT, true));
        updated = Ui.text(this, "Connecting…", 13, Ui.DIM, false);
        titles.addView(updated);
        header.addView(titles, new LinearLayout.LayoutParams(0, -2, 1f));
        selectBtn = Ui.button(this, "Select", false);
        selectBtn.setOnClickListener(v -> setSelecting(!selecting));
        header.addView(selectBtn, new LinearLayout.LayoutParams(-2, Ui.dp(this, 46)));
        int sq = Ui.dp(this, 46);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(sq, sq);
        lp.leftMargin = Ui.dp(this, 8);
        Button refresh = Ui.button(this, "↻", false);
        refresh.setTextSize(18);
        refresh.setOnClickListener(v -> hub.refresh());
        header.addView(refresh, lp);
        Button settings = Ui.button(this, "⚙", false);
        settings.setTextSize(18);
        settings.setOnClickListener(v -> startActivity(new Intent(this, SettingsActivity.class)));
        header.addView(settings, new LinearLayout.LayoutParams(lp));
        root.addView(header);

        ScrollView scroll = new ScrollView(this);
        list = Ui.column(this);
        list.setPadding(0, Ui.dp(this, 14), 0, Ui.dp(this, 24));
        scroll.addView(list);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        bulkBar = buildBulkBar();
        bulkBar.setVisibility(View.GONE);
        root.addView(bulkBar, Ui.fullWidth(this, 0));
        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        Prefs prefs = hub.prefs();
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
        hub.add(this);
        hub.refresh();
        render();
    }

    @Override
    protected void onPause() {
        super.onPause();
        hub.remove(this);
    }

    @Override
    public void onBackPressed() {
        if (selecting) setSelecting(false);
        else super.onBackPressed();
    }

    @Override
    public void onUpdate() {
        updated.setText(hub.status);
        render();
    }

    // ------------------------------------------------------------------ select mode
    private void setSelecting(boolean on) {
        selecting = on;
        selected.clear();
        selectBtn.setText(on ? "Done" : "Select");
        bulkBar.setVisibility(on ? View.VISIBLE : View.GONE);
        updateBulkLabel();
        render();
    }

    private void updateBulkLabel() {
        if (bulkLabel != null)
            bulkLabel.setText(selected.isEmpty() ? "Tick the devices to control"
                    : selected.size() + " selected: " + String.join(", ", selected));
    }

    private LinearLayout buildBulkBar() {
        LinearLayout bar = Ui.column(this);
        int p = Ui.dp(this, 12);
        bar.setPadding(p, p, p, p + Ui.dp(this, 8));
        bar.setBackground(Ui.round(this, Ui.CARD, Ui.LINE, 18));

        LinearLayout top = Ui.row(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        bulkLabel = Ui.text(this, "", 13, Ui.TEXT, false);
        top.addView(bulkLabel, new LinearLayout.LayoutParams(0, -2, 1f));
        Button all = Ui.button(this, "All", false);
        all.setOnClickListener(v -> {
            if (selected.size() == hub.devices.size()) selected.clear();
            else selected.addAll(hub.devices.keySet());
            updateBulkLabel();
            render();
        });
        top.addView(all, new LinearLayout.LayoutParams(Ui.dp(this, 64), -2));
        bar.addView(top);

        LinearLayout r1 = Ui.row(this);
        r1.setPadding(0, Ui.dp(this, 10), 0, 0);
        r1.addView(bulk("🔒\nLock", "lock", false), Ui.weight(this, 3));
        r1.addView(bulk("😴\nSleep", "sleep", false), Ui.weight(this, 3));
        r1.addView(bulk("🔄\nRestart", "restart", false), Ui.weight(this, 3));
        r1.addView(bulk("⏻\nOff", "shutdown", true), Ui.weight(this, 3));
        bar.addView(r1);
        LinearLayout r2 = Ui.row(this);
        r2.setPadding(0, Ui.dp(this, 6), 0, 0);
        r2.addView(bulk("💬 Message", "msg", false), Ui.weight(this, 3));
        r2.addView(bulk("🔔 Ring", "ring", false), Ui.weight(this, 3));
        r2.addView(bulk("⚡ Wake", "wake", false), Ui.weight(this, 3));
        r2.addView(bulk("✋ Cancel", "cancel", false), Ui.weight(this, 3));
        bar.addView(r2);
        return bar;
    }

    private Button bulk(String label, String cmd, boolean danger) {
        Button b = Ui.button(this, label, danger);
        b.setOnClickListener(v -> {
            if (selected.isEmpty()) {
                hub.toast("Tick at least one device first");
                return;
            }
            final List<String> targets = new ArrayList<>(selected);
            runCommand(this, hub, cmd, targets);
        });
        return b;
    }

    /** Runs a command on one or several devices, with confirmation / message input. */
    static void runCommand(Context c, Hub hub, String cmd, List<String> targets) {
        String who = targets.size() == 1 ? targets.get(0) : targets.size() + " devices";
        switch (cmd) {
            case "sleep":
            case "restart":
            case "shutdown": {
                String verb = cmd.equals("shutdown") ? "Shut down"
                        : Character.toUpperCase(cmd.charAt(0)) + cmd.substring(1);
                new AlertDialog.Builder(c, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                        .setTitle(verb + " " + who + "?")
                        .setMessage("It happens after a short countdown. You can still cancel.")
                        .setPositiveButton(verb, (d, w) -> {
                            for (String t : targets) hub.send(cmd, t, null);
                        })
                        .setNegativeButton("No", null)
                        .show();
                break;
            }
            case "msg": {
                EditText input = new EditText(c);
                input.setHint("e.g. Dinner is ready 🍽️");
                input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                        | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
                input.setTextColor(Ui.TEXT);
                input.setHintTextColor(Ui.DIM);
                int p = Ui.dp(c, 20);
                LinearLayout box = Ui.column(c);
                box.setPadding(p, Ui.dp(c, 8), p, 0);
                box.addView(input);
                new AlertDialog.Builder(c, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                        .setTitle("Message on " + who + "'s screen")
                        .setView(box)
                        .setPositiveButton("Send", (d, w) -> {
                            String text = input.getText().toString().trim();
                            if (text.isEmpty()) return;
                            JSONObject extra = new JSONObject();
                            try {
                                extra.put("text", text);
                            } catch (Exception ignored) {
                            }
                            for (String t : targets) hub.send("msg", t, extra);
                        })
                        .setNegativeButton("Cancel", null)
                        .show();
                break;
            }
            case "wake":
                for (String t : targets) hub.wake(t);
                break;
            default:
                for (String t : targets) hub.send(cmd, t, null);
        }
    }

    // ------------------------------------------------------------------ cards
    private void render() {
        list.removeAllViews();
        if (hub.devices.isEmpty()) {
            TextView empty = Ui.text(this, "No devices yet.\nMake sure the agents are running and use the same topic.",
                    15, Ui.DIM, false);
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, Ui.dp(this, 40), 0, 0);
            list.addView(empty);
            return;
        }
        for (Map.Entry<String, JSONObject> e : hub.devices.entrySet()) {
            list.addView(card(e.getKey(), e.getValue()), Ui.fullWidth(this, 0));
            list.addView(new View(this), new LinearLayout.LayoutParams(1, Ui.dp(this, 14)));
        }
    }

    static int stateColor(String st) {
        switch (st) {
            case "up": return Ui.GREEN;
            case "sleep": return Ui.AMBER;
            default: return Ui.RED;
        }
    }

    static String stateLabel(String st) {
        switch (st) {
            case "up": return "● Online";
            case "sleep": return "● Sleeping";
            case "off": return "● Turned off";
            default: return "● Offline";
        }
    }

    private View card(String name, JSONObject hb) {
        String st = Hub.state(hb);
        boolean live = st.equals("up");
        LinearLayout card = Ui.card(this);
        if (selected.contains(name)) card.setBackground(Ui.round(this, 0xFF15233D, Ui.BLUE, 18));

        LinearLayout top = Ui.row(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        if (selecting) {
            CheckBox cb = new CheckBox(this);
            cb.setChecked(selected.contains(name));
            cb.setClickable(false);
            top.addView(cb);
        }
        TextView icon = Ui.text(this, hb.optString("e", "💻"), 30, Ui.TEXT, false);
        icon.setPadding(0, 0, Ui.dp(this, 12), 0);
        top.addView(icon);
        LinearLayout names = Ui.column(this);
        names.addView(Ui.text(this, name, 17, Ui.TEXT, true));
        names.addView(Ui.text(this, stateLabel(st), 13, stateColor(st), false));
        top.addView(names, new LinearLayout.LayoutParams(0, -2, 1f));
        if (!selecting) top.addView(Ui.text(this, "›", 26, Ui.DIM, false));
        card.addView(top);

        TextView act = Ui.text(this, Ui.activity(hb, live), 16, Ui.TEXT, false);
        act.setPadding(0, Ui.dp(this, 12), 0, Ui.dp(this, 2));
        card.addView(act);

        if (live && !Ui.stats(hb).isEmpty()) card.addView(Ui.text(this, Ui.stats(hb), 13, Ui.TEXT, false));
        StringBuilder meta = new StringBuilder();
        if (!hb.isNull("bat") && hb.has("bat"))
            meta.append("🔋 ").append(hb.optInt("bat")).append('%').append(hb.optBoolean("chg") ? " ⚡" : "").append("   ");
        if (live && hb.optLong("idle") >= 60) meta.append("💤 idle ").append(Ui.duration(hb.optLong("idle"))).append("   ");
        meta.append("seen ").append(Ui.ago(Hub.now() - hb.optLong("_t")));
        card.addView(Ui.text(this, meta.toString(), 13, Ui.DIM, false));
        String today = Ui.today(hb);
        if (!today.isEmpty()) card.addView(Ui.text(this, today, 13, Ui.DIM, false));
        String badge = Ui.wakeBadge(hub.wol(name), hub.prefs().get("wt:" + name));
        if (!badge.isEmpty()) card.addView(Ui.text(this, badge, 13, Ui.DIM, false));

        if (selecting) {
            card.setOnClickListener(v -> {
                if (!selected.remove(name)) selected.add(name);
                updateBulkLabel();
                render();
            });
            return card;
        }
        card.setOnClickListener(v -> startActivity(new Intent(this, DeviceActivity.class).putExtra("d", name)));
        List<String> me = new ArrayList<>();
        me.add(name);

        LinearLayout row1 = Ui.row(this);
        row1.setPadding(0, Ui.dp(this, 14), 0, 0);
        if (live) {
            row1.addView(action("🔒\nLock", "lock", me, false), Ui.weight(this, 4));
            row1.addView(action("😴\nSleep", "sleep", me, false), Ui.weight(this, 4));
            row1.addView(action("🔄\nRestart", "restart", me, false), Ui.weight(this, 4));
            row1.addView(action("⏻\nOff", "shutdown", me, true), Ui.weight(this, 4));
        } else {
            JSONObject w = hub.wol(name);
            Button wake = action("⚡ Wake up", "wake", me, false);
            if (w == null || w.optString("mac").isEmpty()) wake.setAlpha(0.5f);
            row1.addView(wake, Ui.weight(this, 4));
        }
        card.addView(row1);

        if (live) {
            LinearLayout row2 = Ui.row(this);
            row2.setPadding(0, Ui.dp(this, 8), 0, 0);
            row2.addView(action("💬 Message", "msg", me, false), Ui.weight(this, 4));
            row2.addView(action("🔔 Ring", "ring", me, false), Ui.weight(this, 4));
            row2.addView(action("✋ Cancel", "cancel", me, false), Ui.weight(this, 4));
            card.addView(row2);
        }
        return card;
    }

    private Button action(String label, String cmd, List<String> targets, boolean danger) {
        Button b = Ui.button(this, label, danger);
        b.setOnClickListener(v -> runCommand(this, hub, cmd, targets));
        return b;
    }
}
