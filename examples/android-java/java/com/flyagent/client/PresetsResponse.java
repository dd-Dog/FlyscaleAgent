package com.flyagent.client;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** GET /api/presets 响应 */
public final class PresetsResponse {

    public static final class PresetItem {
        @SerializedName("id")
        public String id;

        @SerializedName("name")
        public String name;
    }

    @SerializedName("presets")
    public List<PresetItem> presets;
}
