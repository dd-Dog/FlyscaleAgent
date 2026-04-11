package com.flyagent.client;

import java.io.File;
import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * 对 {@link FlyAgentApi} 的异步封装。同步调用请直接使用 {@code FlyAgentRetrofit.create(...)} 返回的 api
 * 并在后台线程 {@code execute()}。
 */
public final class FlyAgentClient {

    private final FlyAgentApi api;

    public FlyAgentClient(String baseUrl, String apiKey) {
        this.api = FlyAgentRetrofit.create(baseUrl, apiKey);
    }

    public FlyAgentApi api() {
        return api;
    }

    public void chat(ChatRequest request, FlyAgentListener<ChatResponse> listener) {
        api.chat(request).enqueue(new Callback<ChatResponse>() {
            @Override
            public void onResponse(Call<ChatResponse> call, Response<ChatResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    listener.onSuccess(response.body());
                } else {
                    listener.onFailure(new IOException("chat HTTP " + response.code()));
                }
            }

            @Override
            public void onFailure(Call<ChatResponse> call, Throwable t) {
                listener.onFailure(t);
            }
        });
    }

    public void presets(FlyAgentListener<PresetsResponse> listener) {
        api.presets().enqueue(new Callback<PresetsResponse>() {
            @Override
            public void onResponse(Call<PresetsResponse> call, Response<PresetsResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    listener.onSuccess(response.body());
                } else {
                    listener.onFailure(new IOException("presets HTTP " + response.code()));
                }
            }

            @Override
            public void onFailure(Call<PresetsResponse> call, Throwable t) {
                listener.onFailure(t);
            }
        });
    }

    public void asrFlash(File audioFile, String fileMimeType, String format, int sampleRate,
                         FlyAgentListener<AsrFlashResponse> listener) {
        RequestBody rb = RequestBody.create(audioFile, MediaType.parse(fileMimeType));
        MultipartBody.Part part = MultipartBody.Part.createFormData("file", audioFile.getName(), rb);
        api.asrFlash(part, format, sampleRate).enqueue(new Callback<AsrFlashResponse>() {
            @Override
            public void onResponse(Call<AsrFlashResponse> call, Response<AsrFlashResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    listener.onSuccess(response.body());
                } else {
                    listener.onFailure(new IOException("asrFlash HTTP " + response.code()));
                }
            }

            @Override
            public void onFailure(Call<AsrFlashResponse> call, Throwable t) {
                listener.onFailure(t);
            }
        });
    }

    public void voiceChat(File audioFile, String fileMimeType, VoiceChatOptions options,
                          FlyAgentListener<VoiceChatResult> listener) {
        VoiceChatOptions o = options != null ? options : VoiceChatOptions.defaults();
        RequestBody rb = RequestBody.create(audioFile, MediaType.parse(fileMimeType));
        MultipartBody.Part part = MultipartBody.Part.createFormData("file", audioFile.getName(), rb);

        api.voiceChat(
                part,
                o.asrEngine,
                o.format,
                o.sampleRate,
                o.provider,
                o.preset,
                o.voice
        ).enqueue(new Callback<ResponseBody>() {
            @Override
            public void onResponse(Call<ResponseBody> call, Response<ResponseBody> response) {
                if (!response.isSuccessful() || response.body() == null) {
                    listener.onFailure(new IOException("voiceChat HTTP " + response.code()));
                    return;
                }
                try {
                    byte[] bytes = response.body().bytes();
                    okhttp3.MediaType mt = response.body().contentType();
                    String contentType = mt != null ? mt.toString() : "application/octet-stream";

                    String asrEnc = response.headers().get("X-ASR-Text-UrlEncoded");
                    String replyEnc = response.headers().get("X-Reply-Text-UrlEncoded");
                    String asrText = decodeHeaderUtf8(asrEnc);
                    String replyText = decodeHeaderUtf8(replyEnc);
                    String provider = response.headers().get("X-Provider");
                    String preset = response.headers().get("X-Preset");
                    long totalMs = parseLongHeader(response.headers().get("X-Total-Latency-Ms"));

                    listener.onSuccess(new VoiceChatResult(
                            bytes, contentType, asrText, replyText,
                            provider != null ? provider : "",
                            preset != null ? preset : "",
                            totalMs
                    ));
                } catch (IOException e) {
                    listener.onFailure(e);
                }
            }

            @Override
            public void onFailure(Call<ResponseBody> call, Throwable t) {
                listener.onFailure(t);
            }
        });
    }

    private static String decodeHeaderUtf8(String encoded) {
        if (encoded == null || encoded.isEmpty()) {
            return "";
        }
        try {
            return URLDecoder.decode(encoded, StandardCharsets.UTF_8.name());
        } catch (Exception e) {
            return encoded;
        }
    }

    private static long parseLongHeader(String v) {
        if (v == null || v.isEmpty()) {
            return 0L;
        }
        try {
            return Long.parseLong(v);
        } catch (NumberFormatException e) {
            return 0L;
        }
    }
}
