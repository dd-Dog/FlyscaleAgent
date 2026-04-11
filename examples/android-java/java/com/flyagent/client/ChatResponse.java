package com.flyagent.client;

import com.google.gson.annotations.SerializedName;

/** POST /api/chat 响应 */
public final class ChatResponse {

    @SerializedName("provider")
    public String provider;

    @SerializedName("text")
    public String text;

    @SerializedName("latency_ms")
    public long latencyMs;

    @SerializedName("preset")
    public String preset;

    @SerializedName("audio_base64")
    public String audioBase64;

    @SerializedName("audio_mime")
    public String audioMime;
}
