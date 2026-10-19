package com.rami.devicewatch;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * One shared connection for all screens: polls the status topic while any screen is open
 * (every 30 s, every 3 s right after you send a command), keeps the latest state of each
 * laptop, and sends commands with retries.
 */
final class Hub {
    interface Listener {
        void onUpdate();

        /** Every message from a laptop: status, history replies, receipts. */
        default void onEvent(String type, JSONObject msg) {}
    }

    /** No heartbeat for this long = offline (> 2x agent heartbeat). */
    static final long STALE_SEC = 35 * 60;

    private static Hub instance;

    static Hub get(Context c) {
        if (instance == null) instance = new Hub(c.getApplicationContext());
        return instance;
    }

    final Map<String, JSONObject> devices = new TreeMap<>();
    String status = "Connecting…";

    private final Context app;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final ExecutorService cmdIo = Executors.newSingleThreadExecutor();
    private final List<Listener> listeners = new ArrayList<>();
    private final Runnable pollTask = this::poll;
    private String lastId, signature;
    private long fastUntil;
    private boolean inFlight;

    private Hub(Context app) {
        this.app = app;
    }

    Prefs prefs() {
        return new Prefs(app);
    }

    void add(Listener l) {
        if (!listeners.contains(l)) listeners.add(l);
        Prefs p = prefs();
        if (!p.signature().equals(signature)) {         // settings changed: start fresh
            signature = p.signature();
            devices.clear();
            lastId = null;
        }
        poll();
    }

    void remove(Listener l) {
        listeners.remove(l);
        if (listeners.isEmpty()) ui.removeCallbacks(pollTask);
    }

    // ------------------------------------------------------------------ state helpers
    static long now() {
        return System.currentTimeMillis() / 1000;
    }

    /** "up", "sleep", "off" or "lost". */
    static String state(JSONObject hb) {
        String s = hb.optString("s", "up");
        if (s.equals("sleep") || s.equals("off")) return s;
        return now() - hb.optLong("_t") > STALE_SEC ? "lost" : "up";
    }

    /** Last known wake-up report for a laptop (kept even while it's offline). */
    JSONObject wol(String device) {
        JSONObject hb = devices.get(device);
        if (hb != null && hb.optJSONObject("wol") != null) return hb.optJSONObject("wol");
        try {
            String s = prefs().get("wol:" + device);
            return s == null ? null : new JSONObject(s);
        } catch (Exception e) {
            return null;
        }
    }

    // ------------------------------------------------------------------ commands
    void send(String cmd, String to, JSONObject extra) {
        Prefs p = prefs();
        cmdIo.execute(() -> {
            Exception last = null;
            for (int attempt = 0; attempt < 3; attempt++) {           // retry brief network hiccups
                try {
                    Api.command(p, cmd, to, "app", extra);
                    last = null;
                    break;
                } catch (Exception e) {
                    last = e;
                    try {
                        Thread.sleep(1200L * (attempt + 1));
                    } catch (InterruptedException ie) {
                        return;
                    }
                }
            }
            final Exception err = last;
            ui.post(() -> {
                if (err != null) {
                    String m = String.valueOf(err.getMessage());
                    toast(m.contains("429") ? "Server busy (rate limit). Try again in a minute."
                            : "Couldn't send. Check your internet.");
                    return;
                }
                if (!cmd.equals("status") && !cmd.equals("history") && !cmd.equals("wake"))
                    toast("Sent “" + cmd + "” to " + (to.equals("*") ? "all" : to) + "…");
                fastUntil = System.currentTimeMillis() + 25000;
                schedule(1200);
            });
        });
    }

    /** Wake a sleeping laptop: direct packet from the phone + ask the other laptops to relay. */
    void wake(String device) {
        JSONObject w = wol(device);
        if (w == null || w.optString("mac").isEmpty()) {
            toast("No network address known for " + device + " yet.");
            return;
        }
        final String mac = w.optString("mac"), bcast = w.optString("bcast");
        new Thread(() -> Wol.send(mac, bcast)).start();
        JSONObject extra = new JSONObject();
        try {
            extra.put("target", device).put("mac", mac).put("bcast", bcast);
        } catch (Exception ignored) {
        }
        send("wake", "*", extra);
        toast("⚡ Wake-up sent to " + device);
    }

    // ------------------------------------------------------------------ polling
    void refresh() {
        send("status", "*", null);
    }

    private void schedule(long ms) {
        ui.removeCallbacks(pollTask);
        if (!listeners.isEmpty()) ui.postDelayed(pollTask, ms);
    }

    private void poll() {
        ui.removeCallbacks(pollTask);
        if (inFlight) {                       // a poll is already running; it reschedules itself
            return;
        }
        Prefs p = prefs();
        if (!p.configured()) return;
        inFlight = true;
        final String since = lastId != null ? lastId : (STALE_SEC * 2 / 60) + "m";
        final String url = p.server() + "/" + p.topic() + "-hb/json?poll=1&since=" + since;
        final String token = p.token();
        io.execute(() -> {
            String body = null;
            try {
                body = Api.get(url, token);
            } catch (Exception ignored) {
            }
            final String result = body;
            ui.post(() -> {
                inFlight = false;
                if (result == null) {
                    status = "Offline - retrying…";
                } else {
                    ingest(result);
                    status = "Updated " + java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT)
                            .format(new java.util.Date());
                }
                for (Listener l : new ArrayList<>(listeners)) l.onUpdate();
                schedule(System.currentTimeMillis() < fastUntil ? 3000 : 30000);
            });
        });
    }

    private void ingest(String ndjson) {
        for (String line : ndjson.split("\n")) {
            if (line.isEmpty()) continue;
            JSONObject ev, msg;
            try {
                ev = new JSONObject(line);
                if (!"message".equals(ev.optString("event"))) continue;
                lastId = ev.optString("id", lastId);
                msg = new JSONObject(ev.optString("message"));
                msg.put("_t", ev.optLong("time"));
            } catch (Exception e) {
                continue;
            }
            String name = msg.optString("d"), type = msg.optString("type");
            if (name.isEmpty() || type.equals("dryrun")) continue;
            boolean recent = now() - msg.optLong("_t") < 60;
            switch (type) {
                case "ack":
                    if (recent) toast("✓ " + name + " received “" + msg.optString("cmd") + "”");
                    break;
                case "relay":
                    if (recent) toast("📡 " + name + " sent a wake-up to " + msg.optString("target"));
                    break;
                case "hist":
                case "histw":
                    break;
                default:
                    merge(name, msg);
            }
            for (Listener l : new ArrayList<>(listeners)) l.onEvent(type, msg);
        }
    }

    /** Quick updates (app started/stopped) don't carry stats: keep the previous ones. */
    private void merge(String name, JSONObject msg) {
        JSONObject prev = devices.get(name);
        if (prev != null && msg.optLong("b") == prev.optLong("b")) {
            Iterator<String> it = prev.keys();
            while (it.hasNext()) {
                String k = it.next();
                if (!msg.has(k)) {
                    try {
                        msg.put(k, prev.get(k));
                    } catch (Exception ignored) {
                    }
                }
            }
        }
        devices.put(name, msg);
        JSONObject w = msg.optJSONObject("wol");
        if (w != null) prefs().put("wol:" + name, w.toString());
    }

    void toast(String s) {
        Toast.makeText(app, s, Toast.LENGTH_SHORT).show();
    }
}
