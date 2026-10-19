package com.rami.devicewatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** One laptop: live stats, all controls, wake-up support (+ test), and history. */
public class DeviceActivity extends Activity implements Hub.Listener {
    private static final Map<String, JSONObject> histCache = new HashMap<>();   // "name|day" -> reply

    private final Handler ui = new Handler(Looper.getMainLooper());
    private Hub hub;
    private String name;
    private LinearLayout nowBox, controlBox, wakeBox, histBox, weekBox;
    private TextView title, stateText;
    private final Calendar day = Calendar.getInstance();
    private String histRid, weekRid;
    private JSONObject week;

    // wake test
    private int testStep;            // 0 idle, 1 waiting for sleep, 2 settling, 3 waiting for wake
    private long testWakeSentAt;
    private String testMsg;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        hub = Hub.get(this);
        name = getIntent().getStringExtra("d");

        LinearLayout root = Ui.column(this);
        int pad = Ui.dp(this, 16);
        root.setPadding(pad, pad, pad, pad * 2);

        LinearLayout header = Ui.row(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button back = Ui.button(this, "‹", false);
        back.setTextSize(22);
        back.setOnClickListener(v -> finish());
        header.addView(back, new LinearLayout.LayoutParams(Ui.dp(this, 46), Ui.dp(this, 46)));
        LinearLayout names = Ui.column(this);
        names.setPadding(Ui.dp(this, 12), 0, 0, 0);
        title = Ui.text(this, name, 22, Ui.TEXT, true);
        stateText = Ui.text(this, "", 13, Ui.DIM, false);
        names.addView(title);
        names.addView(stateText);
        header.addView(names, new LinearLayout.LayoutParams(0, -2, 1f));
        Button refresh = Ui.button(this, "↻", false);
        refresh.setTextSize(18);
        refresh.setOnClickListener(v -> {
            hub.send("status", name, null);
            requestHistory(true);
        });
        header.addView(refresh, new LinearLayout.LayoutParams(Ui.dp(this, 46), Ui.dp(this, 46)));
        root.addView(header);

        root.addView(Ui.section(this, "Right now"));
        nowBox = Ui.card(this);
        root.addView(nowBox);
        root.addView(Ui.section(this, "Control"));
        controlBox = Ui.card(this);
        root.addView(controlBox);
        root.addView(Ui.section(this, "Wake-up support"));
        wakeBox = Ui.card(this);
        root.addView(wakeBox);
        root.addView(Ui.section(this, "History"));
        histBox = Ui.card(this);
        root.addView(histBox);
        root.addView(Ui.section(this, "Last 7 days"));
        weekBox = Ui.card(this);
        root.addView(weekBox);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    @Override
    protected void onResume() {
        super.onResume();
        hub.add(this);
        hub.send("status", name, null);
        requestHistory(false);
        renderAll();
    }

    @Override
    protected void onPause() {
        super.onPause();
        hub.remove(this);
        if (testStep != 0) {
            testStep = 0;
            testMsg = "Test stopped (you left the screen).";
        }
        ui.removeCallbacksAndMessages(null);
    }

    private JSONObject hb() {
        JSONObject hb = hub.devices.get(name);
        return hb != null ? hb : new JSONObject();
    }

    @Override
    public void onUpdate() {
        renderNow();
        renderControl();
        renderWake();
    }

    @Override
    public void onEvent(String type, JSONObject msg) {
        if (!name.equals(msg.optString("d"))) return;
        if (type.equals("hist") && msg.optString("rid").equals(histRid)) {
            histCache.put(name + "|" + msg.optString("day"), msg);
            renderHistory();
        } else if (type.equals("histw") && msg.optString("rid").equals(weekRid)) {
            week = msg;
            renderWeek();
        } else if (!type.equals("ack") && !type.equals("relay")) {
            stepWakeTest(msg);
        }
    }

    private void renderAll() {
        renderNow();
        renderControl();
        renderWake();
        renderHistory();
        renderWeek();
    }

    // ------------------------------------------------------------------ right now
    private void renderNow() {
        JSONObject hb = hb();
        String st = hb.length() == 0 ? "lost" : Hub.state(hb);
        boolean live = st.equals("up");
        title.setText(hb.optString("e", "💻") + "  " + name);
        stateText.setText(MainActivity.stateLabel(st)
                + (hb.has("_t") ? " · seen " + Ui.ago(Hub.now() - hb.optLong("_t")) : ""));
        stateText.setTextColor(MainActivity.stateColor(st));
        nowBox.removeAllViews();
        if (!live) {
            nowBox.addView(Ui.text(this, st.equals("sleep") ? "😴 Sleeping. Wake it up from Control below."
                    : "Not reachable right now.", 15, Ui.DIM, false));
            return;
        }
        nowBox.addView(Ui.text(this, Ui.activity(hb, true), 17, Ui.TEXT, true));
        line(nowBox, "CPU", hb.isNull("cpu") || !hb.has("cpu") ? "…" : hb.optInt("cpu") + "%");
        String ram = hb.isNull("ram") || !hb.has("ram") ? "…" : hb.optInt("ram") + "%"
                + (hb.has("ramgb") ? " of " + hb.optString("ramgb") + " GB" : "");
        line(nowBox, "RAM", ram);
        line(nowBox, "GPU", hb.isNull("gpu") || !hb.has("gpu") ? "not available" : hb.optInt("gpu") + "%");
        boolean noTemps = (hb.isNull("ct") || !hb.has("ct")) && (hb.isNull("gt") || !hb.has("gt"));
        if (noTemps) {
            TextView t = line(nowBox, "Temperature", "not available  ⓘ");
            t.setOnClickListener(v -> info("Temperatures",
                    "Windows doesn't share CPU temperature with apps.\n\n"
                            + "To see it: install the free LibreHardwareMonitor on the laptop, open "
                            + "Options → Remote Web Server → Run (port 8085), and tick 'Run On Windows Startup'. "
                            + "DeviceWatch reads the temperatures from it automatically.\n\n"
                            + "NVIDIA graphics card temperature works without it."));
        } else {
            if (!hb.isNull("ct") && hb.has("ct")) line(nowBox, "CPU temp", hb.optInt("ct") + " °C");
            if (!hb.isNull("gt") && hb.has("gt")) line(nowBox, "GPU temp", hb.optInt("gt") + " °C");
        }
        if (!hb.isNull("bat") && hb.has("bat"))
            line(nowBox, "Battery", hb.optInt("bat") + "%" + (hb.optBoolean("chg") ? " ⚡ charging" : ""));
        line(nowBox, "Turned on", Ui.duration(hb.optLong("up")) + " ago");
        if (hb.optLong("idle") >= 60) line(nowBox, "Idle", Ui.duration(hb.optLong("idle")));
        JSONArray apps = hb.optJSONArray("apps");
        if (apps != null && apps.length() > 0) {
            List<String> l = new ArrayList<>();
            for (int i = 0; i < apps.length(); i++) l.add(apps.optString(i));
            line(nowBox, "Open apps", String.join(", ", l));
        }
    }

    private TextView line(LinearLayout box, String label, String value) {
        LinearLayout row = Ui.row(this);
        row.setPadding(0, Ui.dp(this, 7), 0, 0);
        row.addView(Ui.text(this, label, 14, Ui.DIM, false), new LinearLayout.LayoutParams(Ui.dp(this, 110), -2));
        TextView v = Ui.text(this, value, 14, Ui.TEXT, false);
        row.addView(v, new LinearLayout.LayoutParams(0, -2, 1f));
        box.addView(row);
        return v;
    }

    private void info(String t, String msg) {
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle(t).setMessage(msg).setPositiveButton("OK", null).show();
    }

    // ------------------------------------------------------------------ control
    private void renderControl() {
        controlBox.removeAllViews();
        List<String> me = new ArrayList<>();
        me.add(name);
        boolean live = Hub.state(hb()).equals("up") && hb().length() > 0;
        LinearLayout r1 = Ui.row(this), r2 = Ui.row(this), r3 = Ui.row(this);
        r2.setPadding(0, Ui.dp(this, 8), 0, 0);
        r3.setPadding(0, Ui.dp(this, 8), 0, 0);
        if (live) {
            r1.addView(btn("🔒\nLock", "lock", me, false), Ui.weight(this, 4));
            r1.addView(btn("😴\nSleep", "sleep", me, false), Ui.weight(this, 4));
            r1.addView(btn("🔄\nRestart", "restart", me, false), Ui.weight(this, 4));
            r1.addView(btn("⏻\nOff", "shutdown", me, true), Ui.weight(this, 4));
            r2.addView(btn("💬 Message", "msg", me, false), Ui.weight(this, 4));
            r2.addView(btn("🔔 Find (ring)", "ring", me, false), Ui.weight(this, 4));
            r3.addView(btn("✋ Cancel pending", "cancel", me, false), Ui.weight(this, 4));
            r3.addView(btn("📊 Status", "status", me, false), Ui.weight(this, 4));
        } else {
            r1.addView(btn("⚡ Wake up", "wake", me, false), Ui.weight(this, 4));
        }
        controlBox.addView(r1);
        if (live) {
            controlBox.addView(r2);
            controlBox.addView(r3);
        }
    }

    private Button btn(String label, String cmd, List<String> targets, boolean danger) {
        Button b = Ui.button(this, label, danger);
        b.setOnClickListener(v -> MainActivity.runCommand(this, hub, cmd, targets));
        return b;
    }

    // ------------------------------------------------------------------ wake-up support
    private void renderWake() {
        wakeBox.removeAllViews();
        JSONObject w = hub.wol(name);
        if (w == null) {
            wakeBox.addView(Ui.text(this, "Waiting for the laptop to report (needs DeviceWatch 1.1 on it).",
                    14, Ui.DIM, false));
            return;
        }
        line(wakeBox, "From sleep", Ui.verdictIcon(w.optString("sleep")));
        line(wakeBox, "From shutdown", Ui.verdictIcon(w.optString("off")));
        String conn = w.optString("conn").equals("wifi") ? "Wi-Fi" : w.optString("conn").equals("ethernet")
                ? "Ethernet (cable)" : w.optString("conn");
        line(wakeBox, "Connection", conn);
        if (!w.optString("adapter").isEmpty()) line(wakeBox, "Adapter", w.optString("adapter"));
        String tested = hub.prefs().get("wt:" + name);
        if (tested != null) {
            String[] p = tested.split("\\|");
            String when = p.length > 1 ? new SimpleDateFormat("d MMM HH:mm", Locale.getDefault())
                    .format(new java.util.Date(Long.parseLong(p[1]) * 1000)) : "";
            line(wakeBox, "Tested", (p[0].equals("ok") ? "✅ Woke up" : "❌ Didn't wake up") + " · " + when);
        }
        JSONArray tips = w.optJSONArray("tips");
        if (tips != null) {
            for (int i = 0; i < tips.length(); i++) {
                TextView t = Ui.text(this, "• " + tips.optString(i), 13, Ui.DIM, false);
                t.setPadding(0, Ui.dp(this, 8), 0, 0);
                wakeBox.addView(t);
            }
        }
        if (testMsg != null) {
            TextView t = Ui.text(this, testMsg, 14, Ui.TEXT, true);
            t.setPadding(0, Ui.dp(this, 12), 0, 0);
            wakeBox.addView(t);
        }
        Button test = Ui.button(this, testStep == 0 ? "🧪 Test wake-up" : "⏳ Testing…", false);
        test.setEnabled(testStep == 0);
        test.setOnClickListener(v -> confirmWakeTest());
        wakeBox.addView(test, Ui.fullWidth(this, 12));
    }

    private void confirmWakeTest() {
        if (!Hub.state(hb()).equals("up")) {
            hub.toast(name + " must be online to start the test.");
            return;
        }
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle("Test wake-up?")
                .setMessage(name + " will go to sleep, then your phone (and your other laptops) will try to "
                        + "wake it up. Takes about 2 minutes. Keep it plugged in, make sure nobody is using it, "
                        + "and stay on this screen.")
                .setPositiveButton("Start", (d, w) -> startWakeTest())
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void startWakeTest() {
        testStep = 1;
        testMsg = "1/3 Putting " + name + " to sleep (30 s countdown)…";
        hub.send("sleep", name, null);
        ui.postDelayed(() -> failTest("It didn't go to sleep. Is something blocking sleep?"), 120_000);
        renderWake();
    }

    private void stepWakeTest(JSONObject msg) {
        String s = msg.optString("s");
        if (testStep == 1 && s.equals("sleep")) {
            testStep = 2;
            testMsg = "2/3 Asleep. Waiting 20 s before waking it…";
            ui.removeCallbacksAndMessages(null);
            ui.postDelayed(() -> {
                testStep = 3;
                testWakeSentAt = Hub.now();
                testMsg = "3/3 Sending wake-up… (waiting up to 2 min)";
                hub.wake(name);
                ui.postDelayed(() -> hub.wake(name), 15_000);        // second try
                ui.postDelayed(() -> failTest("It didn't wake up. Press a key on it to wake it, "
                        + "then check the tips above."), 120_000);
                renderWake();
            }, 20_000);
            renderWake();
        } else if (testStep == 3 && s.equals("up") && msg.optLong("ts") >= testWakeSentAt - 5) {
            ui.removeCallbacksAndMessages(null);
            testStep = 0;
            boolean byNet = "network".equals(msg.optString("ws"));
            testMsg = byNet ? "✅ It works! " + name + " woke up from your wake-up signal."
                    : "✅ It woke up. (Windows didn't confirm it was the network. If nobody touched it, it works.)";
            hub.prefs().put("wt:" + name, "ok|" + Hub.now());
            renderWake();
        }
    }

    private void failTest(String why) {
        if (testStep == 0) return;
        testStep = 0;
        testMsg = "❌ " + why;
        hub.prefs().put("wt:" + name, "fail|" + Hub.now());
        renderWake();
    }

    // ------------------------------------------------------------------ history
    private String dayKey() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(day.getTime());
    }

    private void requestHistory(boolean force) {
        String key = name + "|" + dayKey();
        if (force || !histCache.containsKey(key)) {
            histRid = "h" + System.nanoTime();
            JSONObject extra = new JSONObject();
            try {
                extra.put("day", dayKey()).put("rid", histRid);
            } catch (Exception ignored) {
            }
            hub.send("history", name, extra);
        }
        if (force || week == null) {
            weekRid = "w" + System.nanoTime();
            JSONObject extra = new JSONObject();
            try {
                extra.put("range", "week").put("rid", weekRid);
            } catch (Exception ignored) {
            }
            hub.send("history", name, extra);
        }
    }

    private void moveDay(int delta) {
        day.add(Calendar.DAY_OF_MONTH, delta);
        Calendar today = Calendar.getInstance();
        if (day.after(today)) day.setTime(today.getTime());
        renderHistory();
        String key = name + "|" + dayKey();
        if (!histCache.containsKey(key)) {
            histRid = "h" + System.nanoTime();
            JSONObject extra = new JSONObject();
            try {
                extra.put("day", dayKey()).put("rid", histRid);
            } catch (Exception ignored) {
            }
            hub.send("history", name, extra);
        }
    }

    private void renderHistory() {
        histBox.removeAllViews();
        LinearLayout nav = Ui.row(this);
        nav.setGravity(Gravity.CENTER_VERTICAL);
        Button prev = Ui.button(this, "‹", false);
        prev.setOnClickListener(v -> moveDay(-1));
        Button next = Ui.button(this, "›", false);
        next.setOnClickListener(v -> moveDay(1));
        Calendar today = Calendar.getInstance();
        boolean isToday = dayKey().equals(new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(today.getTime()));
        String label = isToday ? "Today" : new SimpleDateFormat("EEE d MMM", Locale.getDefault()).format(day.getTime());
        TextView l = Ui.text(this, label, 16, Ui.TEXT, true);
        l.setGravity(Gravity.CENTER);
        nav.addView(prev, new LinearLayout.LayoutParams(Ui.dp(this, 48), Ui.dp(this, 42)));
        nav.addView(l, new LinearLayout.LayoutParams(0, -2, 1f));
        next.setEnabled(!isToday);
        next.setAlpha(isToday ? 0.4f : 1f);
        nav.addView(next, new LinearLayout.LayoutParams(Ui.dp(this, 48), Ui.dp(this, 42)));
        histBox.addView(nav);

        JSONObject h = histCache.get(name + "|" + dayKey());
        if (h == null) {
            TextView t = Ui.text(this, Hub.state(hb()).equals("up") ? "Loading…"
                    : "History is stored on the laptop. It appears when " + name + " is online.", 14, Ui.DIM, false);
            t.setPadding(0, Ui.dp(this, 12), 0, 0);
            histBox.addView(t);
            return;
        }
        if (h.has("error")) {
            histBox.addView(Ui.text(this, "Couldn't read history: " + h.optString("error"), 13, Ui.RED, false));
            return;
        }
        TextView on = Ui.text(this, "On for " + Ui.duration(h.optLong("on")), 15, Ui.TEXT, true);
        on.setPadding(0, Ui.dp(this, 12), 0, Ui.dp(this, 6));
        histBox.addView(on);
        JSONObject apps = h.optJSONObject("apps");
        if (apps != null && apps.length() > 0) {
            long max = 1;
            Iterator<String> it = apps.keys();
            while (it.hasNext()) max = Math.max(max, apps.optLong(it.next()));
            it = apps.keys();
            while (it.hasNext()) {
                String app = it.next();
                histBox.addView(Ui.bar(this, app, apps.optLong(app), max, Ui.BLUE));
            }
        }
        JSONArray ev = h.optJSONArray("ev");
        if (ev == null || ev.length() == 0) {
            histBox.addView(Ui.text(this, "Nothing happened this day.", 14, Ui.DIM, false));
            return;
        }
        List<String> quiet = new ArrayList<>();
        JSONArray q = h.optJSONArray("quiet");
        if (q != null) for (int i = 0; i < q.length(); i++) quiet.add(q.optString(i));
        TextView tl = Ui.text(this, "Timeline", 13, Ui.DIM, true);
        tl.setPadding(0, Ui.dp(this, 14), 0, Ui.dp(this, 4));
        histBox.addView(tl);
        for (int i = ev.length() - 1; i >= 0; i--) {                     // newest first
            JSONArray e = ev.optJSONArray(i);
            if (e == null || e.optString(1).equals("rs")) continue;
            boolean dim = (e.optString(1).equals("st") || e.optString(1).equals("cl")) && quiet.contains(e.optString(2));
            LinearLayout row = Ui.row(this);
            row.setPadding(0, Ui.dp(this, 6), 0, 0);
            row.addView(Ui.text(this, Ui.clock(e.optLong(0)), 13, Ui.DIM, false),
                    new LinearLayout.LayoutParams(Ui.dp(this, 52), -2));
            row.addView(Ui.text(this, Ui.event(e), 14, dim ? Ui.DIM : Ui.TEXT, false),
                    new LinearLayout.LayoutParams(0, -2, 1f));
            histBox.addView(row);
        }
        if (h.optInt("trunc") == 1)
            histBox.addView(Ui.text(this, "(Some background-app events hidden to fit.)", 12, Ui.DIM, false));
    }

    private void renderWeek() {
        weekBox.removeAllViews();
        JSONArray days = week == null ? null : week.optJSONArray("week");
        if (days == null) {
            weekBox.addView(Ui.text(this, "Loading…", 14, Ui.DIM, false));
            return;
        }
        long max = 3600;
        for (int i = 0; i < days.length(); i++) max = Math.max(max, days.optJSONObject(i).optLong("on"));
        long total = 0;
        Map<String, Long> appTotals = new HashMap<>();
        SimpleDateFormat in = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        SimpleDateFormat out = new SimpleDateFormat("EEE d", Locale.getDefault());
        for (int i = days.length() - 1; i >= 0; i--) {
            JSONObject d = days.optJSONObject(i);
            String label = d.optString("day");
            try {
                label = out.format(in.parse(label));
            } catch (Exception ignored) {
            }
            weekBox.addView(Ui.bar(this, label, d.optLong("on"), max, Ui.GREEN));
            total += d.optLong("on");
            JSONObject a = d.optJSONObject("apps");
            if (a != null) {
                Iterator<String> it = a.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    appTotals.put(k, appTotals.getOrDefault(k, 0L) + a.optLong(k));
                }
            }
        }
        TextView t = Ui.text(this, "Total on: " + Ui.duration(total), 14, Ui.TEXT, true);
        t.setPadding(0, Ui.dp(this, 10), 0, Ui.dp(this, 4));
        weekBox.addView(t);
        List<Map.Entry<String, Long>> top = new ArrayList<>(appTotals.entrySet());
        top.sort((x, y) -> Long.compare(y.getValue(), x.getValue()));
        long amax = top.isEmpty() ? 1 : top.get(0).getValue();
        for (int i = 0; i < Math.min(5, top.size()); i++)
            weekBox.addView(Ui.bar(this, top.get(i).getKey(), top.get(i).getValue(), amax, Ui.BLUE));
    }
}
