package com.flyagent.client;

import com.google.gson.annotations.SerializedName;

/** POST /api/asr/flash 响应 */
public final class AsrFlashResponse {

    @SerializedName("text")
    public String text;

    @SerializedName("format")
    public String format;

    @SerializedName("sample_rate")
    public int sampleRate;

    @SerializedName("latency_ms")
    public long latencyMs;

    @SerializedName("task_id")
    public String taskId;

    @SerializedName("http_status")
    public int httpStatus;
}
