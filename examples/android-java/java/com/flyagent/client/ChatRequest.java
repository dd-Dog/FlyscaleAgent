package com.flyagent.client;

import com.google.gson.annotations.SerializedName;

/** POST /api/chat 请求体 */
public final class ChatRequest {

    @SerializedName("message")
    public String message;

    @SerializedName("provider")
    public String provider;

    @SerializedName("preset")
    public String preset;

    @SerializedName("system_prompt")
    public String systemPrompt;

    @SerializedName("include_audio")
    public Boolean includeAudio;

    public ChatRequest(String message) {
        this.message = message;
    }
}
