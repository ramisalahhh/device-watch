package com.rami.devicewatch;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

import org.json.JSONException;
import org.json.JSONObject;

/** Tiny ntfy client on top of HttpURLConnection (no libraries). */
final class Api {
    private Api() {}

    static HttpURLConnection open(String url, String token, int readTimeoutMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(readTimeoutMs);
        if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
        return c;
    }

    static String get(String url, String token) throws IOException {
        HttpURLConnection c = open(url, token, 20000);
        try {
            check(c);
            return read(c.getInputStream());
        } finally {
            c.disconnect();
        }
    }

    static void post(String url, String body, String token) throws IOException {
        HttpURLConnection c = open(url, token, 15000);
        try {
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            byte[] data = body.getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(data.length);
            try (OutputStream os = c.getOutputStream()) {
                os.write(data);
            }
            check(c);
            read(c.getInputStream());
        } finally {
            c.disconnect();
        }
    }

    /** Send a command to one device (or "*" for all). */
    static void command(Prefs p, String cmd, String to, String reply) throws IOException {
        JSONObject o = new JSONObject();
        try {
            o.put("cmd", cmd).put("to", to).put("key", p.secret()).put("reply", reply);
        } catch (JSONException ignored) {
        }
        post(p.server() + "/" + p.topic() + "-cmd", o.toString(), p.token());
    }

    static void check(HttpURLConnection c) throws IOException {
        int code = c.getResponseCode();
        if (code >= 400) throw new IOException("HTTP " + code);
    }

    static String read(InputStream in) throws IOException {
        try (InputStream is = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }
}
