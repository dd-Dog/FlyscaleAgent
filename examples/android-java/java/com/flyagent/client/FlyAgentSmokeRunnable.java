package com.flyagent.client;

import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import okhttp3.ResponseBody;
import retrofit2.Response;

/**
 * 在<strong>后台线程</strong>中顺序调用接口并打日志，便于接入现有 App 验证网络与密钥。
 * <pre>
 *   new Thread(new FlyAgentSmokeRunnable(
 *       "http://10.0.2.2:8765",
 *       "你的API密钥",
 *       "你好",
 *       null
 *   )).start();
 * </pre>
 * 真机请把 Base URL 改为电脑局域网 IP；若有测试 WAV，可传入路径以跑语音对话。
 */
public final class FlyAgentSmokeRunnable implements Runnable {

    private static final String TAG = "FlyAgent";

    private final String baseUrl;
    private final String apiKey;
    private final String chatMessage;
    /** 可选：本地 wav 路径，非空则额外请求 /api/voice/chat */
    private final String optionalWavPathForVoiceChat;

    public FlyAgentSmokeRunnable(
            String baseUrl,
            String apiKey,
            String chatMessage,
            String optionalWavPathForVoiceChat
    ) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.chatMessage = chatMessage;
        this.optionalWavPathForVoiceChat = optionalWavPathForVoiceChat;
    }

    @Override
    public void run() {
        FlyAgentApi api = FlyAgentRetrofit.create(baseUrl, apiKey);

        try {
            Response<PresetsResponse> presetsResp = api.presets().execute();
            if (!presetsResp.isSuccessful() || presetsResp.body() == null) {
                Log.e(TAG, "presets failed: HTTP " + presetsResp.code());
                return;
            }
            Log.i(TAG, "presets OK, count=" + (presetsResp.body().presets != null
                    ? presetsResp.body().presets.size() : 0));

            ChatRequest chatReq = new ChatRequest(chatMessage);
            chatReq.preset = "brief";
            chatReq.includeAudio = false;
            Response<ChatResponse> chatResp = api.chat(chatReq).execute();
            if (!chatResp.isSuccessful() || chatResp.body() == null) {
                Log.e(TAG, "chat failed: HTTP " + chatResp.code());
                return;
            }
            Log.i(TAG, "chat OK: " + chatResp.body().text);

            if (optionalWavPathForVoiceChat != null && !optionalWavPathForVoiceChat.isEmpty()) {
                File wav = new File(optionalWavPathForVoiceChat);
                if (!wav.isFile()) {
                    Log.w(TAG, "voice chat skipped: file not found " + optionalWavPathForVoiceChat);
                    return;
                }
                VoiceChatOptions o = VoiceChatOptions.defaults();
                RequestBody rb = RequestBody.create(wav, MediaType.parse("audio/wav"));
                MultipartBody.Part part = MultipartBody.Part.createFormData("file", wav.getName(), rb);
                Response<ResponseBody> voiceResp = api.voiceChat(
                        part, o.asrEngine, o.format, o.sampleRate, o.provider, o.preset, o.voice
                ).execute();
                if (!voiceResp.isSuccessful() || voiceResp.body() == null) {
                    Log.e(TAG, "voice chat failed: HTTP " + voiceResp.code());
                    return;
                }
                byte[] audio = voiceResp.body().bytes();
                String asrEnc = voiceResp.headers().get("X-ASR-Text-UrlEncoded");
                String replyEnc = voiceResp.headers().get("X-Reply-Text-UrlEncoded");
                String asr = asrEnc != null ? URLDecoder.decode(asrEnc, StandardCharsets.UTF_8.name()) : "";
                String reply = replyEnc != null ? URLDecoder.decode(replyEnc, StandardCharsets.UTF_8.name()) : "";
                Log.i(TAG, "voice chat OK, audio bytes=" + audio.length + " asr=" + asr + " reply=" + reply);
            }
        } catch (IOException e) {
            Log.e(TAG, "smoke test IOException", e);
        }
    }
}
