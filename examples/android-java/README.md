# FlyAgent Android（Java）示例源码

将目录 `java/com/flyagent/client/` **整个复制**到你 App Module 的 `src/main/java/` 下（与现有 `com/...` 并列），保持包名 `com.flyagent.client` 不变；若需改名，请同步修改每个文件首行的 `package`。

## Gradle（`app/build.gradle` 的 `dependencies`）

```gradle
implementation "com.squareup.retrofit2:retrofit:2.11.0"
implementation "com.squareup.retrofit2:converter-gson:2.11.0"
implementation "com.squareup.okhttp3:okhttp:4.12.0"
```

## `AndroidManifest.xml`

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

若使用 **明文 HTTP**（如 `http://192.168.x.x:8765`），在 `application` 上增加：

```xml
android:usesCleartextTraffic="true"
```

（生产环境建议 HTTPS + 关闭明文。）

## 如何“运行”

1. 在任意 `Activity` 的按钮点击里（**不要**在主线程直接阻塞网络）：

   ```java
   new Thread(new FlyAgentSmokeRunnable(
       "http://10.0.2.2:8765",  // 模拟器访问本机；真机改为电脑局域网 IP
       "你的FLYAGENT_API_KEY",
       "你好"
   )).start();
   ```

2. 打开 **Logcat**，过滤标签 **`FlyAgent`**，查看聊天与语音链路日志。

3. 修改 `FlyAgentSmokeRunnable` 顶部的常量，或改为从 `BuildConfig` / 加密配置读取 Base URL 与 Key。

## 文件说明

| 文件 | 作用 |
|------|------|
| `FlyAgentApi` | Retrofit 接口定义 |
| `FlyAgentRetrofit` | OkHttp + Retrofit 构建 |
| `FlyAgentClient` | 异步封装（`enqueue` + 监听器） |
| `FlyAgentSmokeRunnable` | 后台线程一键冒烟测试 |
| 其余 | 模型与拦截器 |
