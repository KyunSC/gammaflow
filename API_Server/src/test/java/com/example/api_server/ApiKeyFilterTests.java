package com.example.api_server;

import com.example.api_server.config.ApiKeyFilter;
import com.example.api_server.controller.HomeController;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ApiKeyFilterTests {
    @RestController
    static class Probe {
        @GetMapping("/api/probe") public String probe() { return "ok"; }
    }

    private MockMvc mvc(String key) {
        return MockMvcBuilders.standaloneSetup(new Probe(), new HomeController())
                .addFilters(new ApiKeyFilter(key)).build();
    }

    @Test void openWhenNoKeyConfigured() throws Exception {
        mvc("").perform(get("/api/probe")).andExpect(status().isOk());
    }

    @Test void requiresMatchingKeyOnApiRoutes() throws Exception {
        var mvc = mvc("s3cret");
        mvc.perform(get("/api/probe")).andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"message\":\"API key required\"}"));
        mvc.perform(get("/api/probe").header("X-Api-Key", "wrong")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/probe").header("X-Api-Key", "s3cret")).andExpect(status().isOk());
    }

    @Test void healthStaysOpenForWarmUpPings() throws Exception {
        mvc("s3cret").perform(get("/health")).andExpect(status().isOk());
    }
}
