package com.flyagent.client;

import java.io.IOException;

import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/**
 * 为每个请求添加 {@code X-API-Key}。若服务端未配置 {@code FLYAGENT_API_KEY}，请勿使用本拦截器。
 */
public final class ApiKeyInterceptor implements Interceptor {

    private final String apiKey;

    public ApiKeyInterceptor(String apiKey) {
        this.apiKey = apiKey;
    }

    @Override
    public Response intercept(Chain chain) throws IOException {
        Request req = chain.request().newBuilder()
                .header("X-API-Key", apiKey)
                .build();
        return chain.proceed(req);
    }
}
