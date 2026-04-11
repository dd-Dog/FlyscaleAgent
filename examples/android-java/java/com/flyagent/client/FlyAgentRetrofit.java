package com.flyagent.client;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/** 构建带 Gson 与可选 API Key 的 {@link FlyAgentApi} */
public final class FlyAgentRetrofit {

    private FlyAgentRetrofit() {
    }

    /**
     * @param baseUrl 形如 {@code http://192.168.1.2:8765/} 或 {@code http://192.168.1.2:8765}（会自动补斜杠）
     * @param apiKey  若为空或 null，不添加 X-API-Key（仅当服务端未启用鉴权时使用）
     */
    public static FlyAgentApi create(String baseUrl, String apiKey) {
        OkHttpClient.Builder http = new OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(180, TimeUnit.SECONDS)
                .writeTimeout(180, TimeUnit.SECONDS);

        if (apiKey != null && !apiKey.isEmpty()) {
            http.addInterceptor(new ApiKeyInterceptor(apiKey));
        }

        String root = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";

        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(root)
                .client(http.build())
                .addConverterFactory(GsonConverterFactory.create())
                .build();

        return retrofit.create(FlyAgentApi.class);
    }
}
