package com.flyagent.client;

import okhttp3.MultipartBody;
import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.Multipart;
import retrofit2.http.POST;
import retrofit2.http.Part;
import retrofit2.http.Query;

/** FlyAgent HTTP 接口（与 {@link FlyAgentRetrofit} 配套使用） */
public interface FlyAgentApi {

    @POST("api/chat")
    Call<ChatResponse> chat(@Body ChatRequest body);

    @GET("api/presets")
    Call<PresetsResponse> presets();

    @Multipart
    @POST("api/asr/flash")
    Call<AsrFlashResponse> asrFlash(
            @Part MultipartBody.Part file,
            @Query("format") String format,
            @Query("sample_rate") int sampleRate
    );

    /**
     * 上传录音 → ASR → LLM → TTS，响应体为音频二进制；
     * 中文 ASR/回复在 Header：X-ASR-Text-UrlEncoded、X-Reply-Text-UrlEncoded（UTF-8 百分号编码）。
     */
    @Multipart
    @POST("api/voice/chat")
    Call<ResponseBody> voiceChat(
            @Part MultipartBody.Part file,
            @Query("asr_engine") String asrEngine,
            @Query("format") String format,
            @Query("sample_rate") Integer sampleRate,
            @Query("provider") String provider,
            @Query("preset") String preset,
            @Query("voice") String voice
    );
}
