package com.flyagent.client;

/** /api/voice/chat 的 Query 参数；未设置的字段传 null，Retrofit 会省略该 query */
public final class VoiceChatOptions {

    public final String asrEngine;
    public final String format;
    public final Integer sampleRate;
    public final String provider;
    public final String preset;
    public final String voice;

    private VoiceChatOptions(
            String asrEngine,
            String format,
            Integer sampleRate,
            String provider,
            String preset,
            String voice
    ) {
        this.asrEngine = asrEngine;
        this.format = format;
        this.sampleRate = sampleRate;
        this.provider = provider;
        this.preset = preset;
        this.voice = voice;
    }

    /** 默认：flash + wav + 16000 + preset brief（preset 在服务端默认也可不传） */
    public static VoiceChatOptions defaults() {
        return new VoiceChatOptions("flash", "wav", 16000, null, "brief", null);
    }

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private String asrEngine = "flash";
        private String format = "wav";
        private Integer sampleRate = 16000;
        private String provider;
        private String preset = "brief";
        private String voice;

        public Builder asrEngine(String v) {
            this.asrEngine = v;
            return this;
        }

        public Builder format(String v) {
            this.format = v;
            return this;
        }

        public Builder sampleRate(int v) {
            this.sampleRate = v;
            return this;
        }

        public Builder provider(String v) {
            this.provider = v;
            return this;
        }

        public Builder preset(String v) {
            this.preset = v;
            return this;
        }

        public Builder voice(String v) {
            this.voice = v;
            return this;
        }

        public VoiceChatOptions build() {
            return new VoiceChatOptions(asrEngine, format, sampleRate, provider, preset, voice);
        }
    }
}
