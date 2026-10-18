package com.rami.devicewatch;

import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

/** Handles taps on notification buttons (Lock, Sleep, Shut down, Cancel). */
public class ActionReceiver extends BroadcastReceiver {
    static final String EXTRA_URL = "url", EXTRA_BODY = "body", EXTRA_LABEL = "label",
            EXTRA_NOTIF = "notif", EXTRA_CLEAR = "clear";

    @Override
    public void onReceive(Context context, Intent intent) {
        final Context app = context.getApplicationContext();
        final String url = intent.getStringExtra(EXTRA_URL);
        final String body = intent.getStringExtra(EXTRA_BODY);
        final String label = intent.getStringExtra(EXTRA_LABEL);
        if (url == null || body == null) return;
        if (intent.getBooleanExtra(EXTRA_CLEAR, true)) {
            NotificationManager nm = app.getSystemService(NotificationManager.class);
            nm.cancel(intent.getIntExtra(EXTRA_NOTIF, 0));
        }
        final PendingResult pending = goAsync();
        final String token = new Prefs(app).token();
        new Thread(() -> {
            String msg = "Couldn't send - no internet?";
            for (int attempt = 0; attempt < 3; attempt++) {     // retry brief network hiccups
                try {
                    Api.post(url, body, token);
                    msg = "Sent: " + label;
                    break;
                } catch (Exception e) {
                    try { Thread.sleep(1200L * (attempt + 1)); } catch (InterruptedException ie) { break; }
                }
            }
            final String m = msg;
            new Handler(Looper.getMainLooper()).post(() -> Toast.makeText(app, m, Toast.LENGTH_SHORT).show());
            pending.finish();
        }).start();
    }
}
