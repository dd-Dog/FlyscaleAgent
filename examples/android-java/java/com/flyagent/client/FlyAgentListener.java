package com.flyagent.client;

/** 异步回调（在 OkHttp 后台线程触发，更新 UI 请自行 post 到主线程） */
public interface FlyAgentListener<T> {

    void onSuccess(T result);

    void onFailure(Throwable error);
}
