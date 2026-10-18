package com.rami.devicewatch;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;

/**
 * Keeps ONE idle HTTP connection to ntfy (server sends a tiny keepalive every ~45 s)
 * and turns each message into a phone notification, which Mi Fitness mirrors to the watch.
 * No polling, no wake-ups of its own, nothing written to storage.
 */
public class WatchService extends Service {
    static final String CH_SERVICE = "service", CH_EVENTS = "events", CH_URGENT = "urgent";
    private static final int SERVICE_ID = 1;

    private volatile boolean running;
    private volatile HttpURLConnection conn;
    private Thread worker;

    /** Start or stop the service to match the user's settings. */
    static void sync(Context c) {
        Prefs p = new Prefs(c);
        Intent i = new Intent(c, WatchService.class);
        try {
            if (p.live() && p.configured()) c.startForegroundService(i);
            else c.stopService(i);
        } catch (Exception ignored) {
            // e.g. background start not allowed right now; next app open retries
        }
    }

    static void createChannels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        NotificationChannel svc = new NotificationChannel(CH_SERVICE, "Connection (silent)",
                NotificationManager.IMPORTANCE_MIN);
        svc.setShowBadge(false);
        NotificationChannel ev = new NotificationChannel(CH_EVENTS, "Device events",
                NotificationManager.IMPORTANCE_DEFAULT);
        NotificationChannel urgent = new NotificationChannel(CH_URGENT, "Urgent (shutdown, battery, offline)",
                NotificationManager.IMPORTANCE_HIGH);
        nm.createNotificationChannel(svc);
        nm.createNotificationChannel(ev);
        nm.createNotificationChannel(urgent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannels(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification n = new Notification.Builder(this, CH_SERVICE)
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("Watching your devices")
                .setContentIntent(openApp(this))
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(SERVICE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(SERVICE_ID, n);
        }
        if (worker == null || !worker.isAlive()) {
            running = true;
            worker = new Thread(this::loop, "dw-stream");
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        HttpURLConnection c = conn;
        if (c != null) new Thread(c::disconnect).start();   // unblocks the reader
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void loop() {
        String lastId = null;
        long backoff = 5;
        while (running) {
            Prefs p = new Prefs(this);
            String url = p.server() + "/" + p.topic() + "/json" + (lastId != null ? "?since=" + lastId : "");
            try {
                conn = Api.open(url, p.token(), 120_000);
                Api.check(conn);
                backoff = 5;
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while (running && (line = r.readLine()) != null) {
                        JSONObject ev;
                        try {
                            ev = new JSONObject(line);
                        } catch (Exception bad) {
                            continue;
                        }
                        if ("message".equals(ev.optString("event"))) {
                            lastId = ev.optString("id", lastId);
                            show(ev);
                        }
                    }
                }
            } catch (Exception ignored) {
                // network dropped / phone offline: retry with backoff
            } finally {
                HttpURLConnection c = conn;
                if (c != null) c.disconnect();
                conn = null;
            }
            if (!running) break;
            try {
                Thread.sleep(backoff * 1000);
            } catch (InterruptedException e) {
                break;
            }
            backoff = Math.min(backoff * 2, 60);
        }
    }

    private void show(JSONObject ev) {
        String title = ev.optString("title", "DeviceWatch");
        String message = ev.optString("message", "");
        int priority = ev.optInt("priority", 3);
        int id = ev.optString("id", String.valueOf(System.nanoTime())).hashCode();
        if (id == SERVICE_ID) id++;

        Notification.Builder b = new Notification.Builder(this, priority >= 4 ? CH_URGENT : CH_EVENTS)
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(new Notification.BigTextStyle().bigText(message))
                .setContentIntent(openApp(this))
                .setAutoCancel(true)
                .setWhen(ev.optLong("time", System.currentTimeMillis() / 1000) * 1000)
                .setShowWhen(true);

        // ntfy "http" action buttons (Lock / Sleep / Shut down / Cancel) -> ActionReceiver
        JSONArray actions = ev.optJSONArray("actions");
        if (actions != null) {
            for (int i = 0; i < actions.length() && i < 3; i++) {
                JSONObject a = actions.optJSONObject(i);
                if (a == null || !"http".equals(a.optString("action"))) continue;
                Intent tap = new Intent(this, ActionReceiver.class)
                        .putExtra(ActionReceiver.EXTRA_URL, a.optString("url"))
                        .putExtra(ActionReceiver.EXTRA_BODY, a.optString("body"))
                        .putExtra(ActionReceiver.EXTRA_LABEL, a.optString("label"))
                        .putExtra(ActionReceiver.EXTRA_NOTIF, id)
                        .putExtra(ActionReceiver.EXTRA_CLEAR, a.optBoolean("clear", true));
                PendingIntent pi = PendingIntent.getBroadcast(this, id * 4 + i, tap,
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
                b.addAction(new Notification.Action.Builder(
                        Icon.createWithResource(this, R.drawable.ic_stat), a.optString("label"), pi).build());
            }
        }
        NotificationManager nm = getSystemService(NotificationManager.class);
        try {
            nm.notify(id, b.build());
        } catch (SecurityException ignored) {
            // notification permission not granted yet
        }
    }

    static PendingIntent openApp(Context c) {
        Intent i = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, 0, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }
}
