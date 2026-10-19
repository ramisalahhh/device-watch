package com.rami.devicewatch;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

/** Sends a Wake-on-LAN "magic packet" straight from the phone (works on home Wi-Fi). */
final class Wol {
    private Wol() {}

    static byte[] packet(String mac) {
        String hex = mac == null ? "" : mac.replaceAll("[^0-9A-Fa-f]", "");
        if (hex.length() != 12) throw new IllegalArgumentException("bad MAC " + mac);
        byte[] m = new byte[6];
        for (int i = 0; i < 6; i++) m[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        byte[] p = new byte[6 + 16 * 6];
        for (int i = 0; i < 6; i++) p[i] = (byte) 0xFF;
        for (int r = 0; r < 16; r++) System.arraycopy(m, 0, p, 6 + r * 6, 6);
        return p;
    }

    /** Returns how many packets were sent (0 = not on a network that allows it). */
    static int send(String mac, String broadcast) {
        int sent = 0;
        byte[] data;
        try {
            data = packet(mac);
        } catch (IllegalArgumentException e) {
            return 0;
        }
        String[] targets = broadcast != null && !broadcast.isEmpty()
                ? new String[]{broadcast, "255.255.255.255"} : new String[]{"255.255.255.255"};
        try (DatagramSocket s = new DatagramSocket()) {
            s.setBroadcast(true);
            for (String t : targets) {
                for (int port : new int[]{9, 7}) {
                    try {
                        s.send(new DatagramPacket(data, data.length, InetAddress.getByName(t), port));
                        sent++;
                    } catch (Exception ignored) {
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return sent;
    }
}
