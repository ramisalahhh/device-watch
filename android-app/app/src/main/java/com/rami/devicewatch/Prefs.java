package com.rami.devicewatch;

import android.content.Context;
import android.content.SharedPreferences;

/** Settings stored on this phone only. */
final class Prefs {
    private final SharedPreferences sp;

    Prefs(Context c) {
        sp = c.getSharedPreferences("dw", Context.MODE_PRIVATE);
    }

    String server() { return sp.getString("server", "https://ntfy.sh"); }
    String topic()  { return sp.getString("topic", ""); }
    String secret() { return sp.getString("secret", ""); }
    String token()  { return sp.getString("token", ""); }
    boolean live()  { return sp.getBoolean("live", true); }

    boolean configured() { return !topic().isEmpty() && !secret().isEmpty(); }

    /** Changes whenever the connection settings change (used to reset cached state). */
    String signature() { return server() + "|" + topic() + "|" + token(); }

    void save(String server, String topic, String secret, String token, boolean live) {
        while (server.endsWith("/")) server = server.substring(0, server.length() - 1);
        sp.edit()
          .putString("server", server.isEmpty() ? "https://ntfy.sh" : server)
          .putString("topic", topic)
          .putString("secret", secret)
          .putString("token", token)
          .putBoolean("live", live)
          .apply();
    }
}
