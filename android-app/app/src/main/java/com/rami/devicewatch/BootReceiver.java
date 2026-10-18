package com.rami.devicewatch;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Restarts live notifications after the phone reboots or the app updates. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        WatchService.sync(context);
    }
}
