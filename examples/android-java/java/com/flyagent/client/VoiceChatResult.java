package com.flyagent.client;

/** POST /api/voice/chat 成功后的业务结果（body + 解码后的头字段） */
public final class VoiceChatResult {

    public final byte[] audioBytes;
    public final String contentType;
    public final String asrText;
    public final String replyText;
    public final String provider;
    public final String preset;
    public final long totalLatencyMs;

    public VoiceChatResult(
            byte[] audioBytes,
            String contentType,
            String asrText,
            String replyText,
            String provider,
            String preset,
            long totalLatencyMs
    ) {
        this.audioBytes = audioBytes;
        this.contentType = contentType;
        this.asrText = asrText;
        this.replyText = replyText;
        this.provider = provider;
        this.preset = preset;
        this.totalLatencyMs = totalLatencyMs;
    }
}
