package com.example.api_server;

import com.example.api_server.config.ApiKeyFilter;
import com.example.api_server.controller.HomeController;
import java.io.IOException;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.autoconfigure.ImportAutoConfiguration;
import org.springframework.boot.autoconfigure.context.PropertyPlaceholderAutoConfiguration;
import org.springframework.boot.http.converter.autoconfigure.HttpMessageConvertersAutoConfiguration;
import org.springframework.boot.jackson.autoconfigure.JacksonAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.tomcat.autoconfigure.servlet.TomcatServletWebServerAutoConfiguration;
import org.springframework.boot.webmvc.autoconfigure.DispatcherServletAutoConfiguration;
import org.springframework.boot.webmvc.autoconfigure.WebMvcAutoConfiguration;
import org.springframework.boot.webmvc.autoconfigure.error.ErrorMvcAutoConfiguration;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

// MockMvc takes the path as given, so anything about URL normalization goes through
// real Tomcat over a raw socket: Java URL clients would clean the target up first.
@SpringBootTest(classes = ApiKeyFilterTests.Server.class, webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "app.api.access-key=" + ApiKeyFilterTests.KEY)
class ApiKeyFilterTests {
    static final String KEY = "s3cret";
    private static final String GUARDED = "guarded-body";
    private static final String KEY_HEADER = "X-Api-Key: " + KEY;

    @RestController
    @CrossOrigin(origins = "http://localhost:5173")
    static class Probe {
        @GetMapping("/api/probe") public String probe() { return GUARDED; }
        @GetMapping("/api/probe/{id}") public String probeId(@PathVariable String id) { return GUARDED; }
    }

    @Configuration(proxyBeanMethods = false)
    @ImportAutoConfiguration({PropertyPlaceholderAutoConfiguration.class, TomcatServletWebServerAutoConfiguration.class,
            DispatcherServletAutoConfiguration.class, WebMvcAutoConfiguration.class, ErrorMvcAutoConfiguration.class,
            HttpMessageConvertersAutoConfiguration.class, JacksonAutoConfiguration.class})
    @Import({ApiKeyFilter.class, Probe.class, HomeController.class})
    static class Server {
    }

    private record Reply(int status, String text) {
        boolean leaked() { return text.contains(GUARDED); }
    }

    @LocalServerPort private int port;

    private Reply send(String method, String target, String... headers) throws IOException {
        var head = new StringBuilder(method + " " + target + " HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n");
        for (String header : headers) head.append(header).append("\r\n");
        try (var socket = new Socket("127.0.0.1", port)) {
            socket.setSoTimeout(5_000);
            socket.getOutputStream().write(head.append("\r\n").toString().getBytes(StandardCharsets.ISO_8859_1));
            String text = new String(socket.getInputStream().readAllBytes(), StandardCharsets.ISO_8859_1);
            return new Reply(Integer.parseInt(text.split(" ", 3)[1]), text);
        }
    }

    private MockMvc mvc(String key) {
        return MockMvcBuilders.standaloneSetup(new Probe(), new HomeController())
                .addFilters(new ApiKeyFilter(key)).build();
    }

    @Test void openWhenNoKeyConfigured() throws Exception {
        var mvc = mvc("");
        mvc.perform(get("/api/probe")).andExpect(status().isOk());
        mvc.perform(get("/nope")).andExpect(status().isNotFound());
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
        mvc("s3cret").perform(get("/")).andExpect(status().isOk());
    }

    @ParameterizedTest
    @ValueSource(strings = {"/api/probe", "/api/probe/1", "/api;x=1/probe", "/api;/probe", "/api/probe;x=1",
            "/api;x=1/probe;y=2", "/%61pi/probe", "/%61%70%69/%70%72%6f%62%65", "/api/%70robe", "//api/probe",
            "/./api/probe", "/api/./probe", "/nope/../api/probe", "/api/probe/1/..", "/health/../api/probe",
            "/health;x=1/../api/probe", "/%68ealth/../api/probe", "/health/%2e%2e/api/probe"})
    void urlsThatNormalizeToApiNeedTheKey(String target) throws IOException {
        Reply denied = send("GET", target);
        assertEquals(401, denied.status(), target);
        assertTrue(denied.text().contains("API key required"), target);
        assertFalse(denied.leaked(), target);
    }

    // The same spellings do reach the controller, which is what makes the denial above matter.
    @ParameterizedTest
    @ValueSource(strings = {"/api/probe", "/api;x=1/probe", "/api;/probe", "/api/probe;x=1", "/api;x=1/probe;y=2",
            "/%61pi/probe", "/%61%70%69/%70%72%6f%62%65", "/api/%70robe"})
    void urlsThatRouteToApiReachItWithTheKey(String target) throws IOException {
        Reply allowed = send("GET", target, KEY_HEADER);
        assertEquals(200, allowed.status(), target);
        assertTrue(allowed.leaked(), target);
        assertEquals(401, send("GET", target, "X-Api-Key: wrong").status(), target);
    }

    // Default deny: nothing past the public paths answers without the key, routed or not.
    @ParameterizedTest
    @ValueSource(strings = {"/%2561pi/probe", "/%2561pi%252Fprobe", "/API/probe", "/Api/probe", "/HEALTH", "/Health",
            "/health/", "/healthz", "/health.json", "/%2568ealth", "/health%3Bx=1", "/api%3Bx=1/probe", "/nope", "/error"})
    void everythingElseIsDeniedByDefault(String target) throws IOException {
        Reply denied = send("GET", target);
        assertEquals(401, denied.status(), target);
        assertFalse(denied.leaked(), target);
    }

    @Test void keyedMissReportsNotFound() throws IOException {
        assertEquals(404, send("GET", "/nope", KEY_HEADER).status());
    }

    // Tomcat refuses these before any filter runs; pinned so a connector change can't open a route.
    @ParameterizedTest
    @ValueSource(strings = {"/api%2Fprobe", "/%61pi%2Fprobe", "/api%2fprobe", "/health%2F..%2Fapi%2Fprobe",
            "/api%5Cprobe", "/api/probe%00", "/../api/probe"})
    void malformedUrlsAreRejected(String target) throws IOException {
        Reply rejected = send("GET", target);
        assertEquals(400, rejected.status(), target);
        assertFalse(rejected.leaked(), target);
    }

    @ParameterizedTest
    @ValueSource(strings = {"/", "/health", "/health;x=1", "/%68ealth"})
    void publicPathsStayOpenHoweverTheyAreSpelled(String target) throws IOException {
        Reply open = send("GET", target);
        assertEquals(200, open.status(), target);
        assertFalse(open.leaked(), target);
    }

    // These normalize to a public path, so the filter lets them by. Spring matches the raw
    // segments instead, finds no route, and nothing under /api may answer.
    @ParameterizedTest
    @ValueSource(strings = {"/api/probe/../../health", "/api/probe/1/../../../health", "/api/probe/../..",
            "/api/probe/%2e%2e/%2e%2e/health", "/api;x=1/probe/../../health", "/%61pi/probe/../..",
            "/./health", "/nope/../health", "/;x=1"})
    void traversalToAPublicPathNeverReachesApiRoutes(String target) throws IOException {
        Reply reply = send("GET", target);
        assertEquals(404, reply.status(), target);
        assertFalse(reply.leaked(), target);
    }

    @ParameterizedTest
    @ValueSource(strings = {"HEAD", "POST", "PUT", "DELETE", "PATCH"})
    void onlyOptionsSkipsTheKey(String method) throws IOException {
        assertEquals(401, send(method, "/api/probe").status(), method);
        assertEquals(401, send(method, "/%61pi/probe").status(), method);
    }

    @Test void headStaysOpenOnHealthForMonitors() throws IOException {
        assertEquals(200, send("HEAD", "/health").status());
    }

    @Test void corsPreflightStaysKeyless() throws IOException {
        Reply preflight = send("OPTIONS", "/api/probe", "Origin: http://localhost:5173",
                "Access-Control-Request-Method: GET");
        assertEquals(200, preflight.status());
        assertTrue(preflight.text().contains("Access-Control-Allow-Origin: http://localhost:5173"));
        assertFalse(preflight.leaked());
    }

    @Test void plainOptionsAnswersWithoutTheBody() throws IOException {
        Reply options = send("OPTIONS", "/api/probe");
        assertEquals(200, options.status());
        assertTrue(options.text().contains("Allow:"));
        assertFalse(options.leaked());
    }
}
