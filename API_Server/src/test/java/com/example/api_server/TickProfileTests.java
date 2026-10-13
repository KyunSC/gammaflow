package com.example.api_server;

import com.example.api_server.controller.VolumeProfileController;
import com.example.api_server.exception.GlobalExceptionHandler;
import com.example.api_server.exception.MarketDataException;
import com.example.api_server.service.TickProfileService;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.LongStream;
import java.util.zip.GZIPOutputStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class TickProfileTests {
    // 2026-07-06 13:25 UTC; the session covers three minutes.
    static final long T0 = 1_783_344_300L;

    @TempDir Path directory;
    MockMvc mvc;
    TickProfileService service;

    @BeforeEach void publish() throws Exception {
        Path nq = Files.createDirectories(directory.resolve("NQ"));
        Files.writeString(nq.resolve("index.json"), """
                {"v":1,"symbol":"NQ","tickSize":0.25,"sessions":[{"date":"2026-07-06","start":%d,"end":%d,"file":"2026-07-06.json.gz"}]}
                """.formatted(T0, T0 + 180));
        writeDay(nq, """
                {"v":1,"minutes":[[%d,400,3,0,0,3],[%d,402,1,0,4],[%d,399,7]],"delta":[[-1,0,0,3],[1,0,-2],[7]]}
                """.formatted(T0, T0 + 60, T0 + 120));
        service = new TickProfileService(directory.toString(), true);
        mvc = MockMvcBuilders.standaloneSetup(new VolumeProfileController(service))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    static void writeDay(Path folder, String day) throws Exception {
        writeDay(folder, "2026-07-06.json.gz", day);
    }

    static void writeDay(Path folder, String file, String day) throws Exception {
        var bytes = new ByteArrayOutputStream();
        try (var gz = new GZIPOutputStream(bytes)) { gz.write(day.getBytes(StandardCharsets.UTF_8)); }
        Files.write(folder.resolve(file), bytes.toByteArray());
    }

    /** n one-minute sessions a day apart from T0; session i trades i + 1 contracts at tick 400. */
    static Path publishDailySessions(Path root, int n) throws Exception {
        Path es = Files.createDirectories(root.resolve("ES"));
        List<String> entries = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            long start = T0 + i * 86_400L;
            String file = "2026-07-06-" + (i + 1) + ".json.gz";
            entries.add("{\"start\":%d,\"end\":%d,\"file\":\"%s\"}".formatted(start, start + 60, file));
            writeDay(es, file, "{\"v\":1,\"minutes\":[[%d,400,%d]]}".formatted(start, i + 1));
        }
        Files.writeString(es.resolve("index.json"),
                "{\"v\":1,\"symbol\":\"ES\",\"tickSize\":0.25,\"sessions\":[" + String.join(",", entries) + "]}");
        return root;
    }

    static List<long[]> oneBarPerSession(int n) {
        return LongStream.range(0, n).mapToObj(i -> new long[]{T0 + i * 86_400L, 60, 1}).toList();
    }

    @Test void sumsMinutesIntoBarsOnAMergedTickGrid() {
        var bars = service.bars("NQ", List.of(new long[]{T0, 120, 1}));
        assertEquals(1, bars.size());
        // ticks 400..404: minute 0 gives 3,0,0,3 at 400..403; minute 1 gives 1,0,4 at 402..404.
        assertArrayEquals(new long[]{T0, 400, 3, 0, 1, 3, 4}, bars.get(0).volume());
        // Delta sums on the same grid: -1,0,0,3 at 400..403 plus 1,0,-2 at 402..404.
        assertArrayEquals(new long[]{-1, 0, 1, 3, -2}, bars.get(0).delta());
    }

    @Test void sessionsWithoutSideDataHaveNoDelta() throws Exception {
        writeDay(directory.resolve("NQ"), """
                {"v":1,"minutes":[[%d,400,3]]}
                """.formatted(T0));
        var bars = new TickProfileService(directory.toString(), true).bars("NQ", List.of(new long[]{T0, 60, 1}));
        assertArrayEquals(new long[]{T0, 400, 3}, bars.get(0).volume());
        assertNull(bars.get(0).delta());
    }

    @Test void answersOnlyBarsInsideASession() {
        // 1m bars from one minute before the session to one after: only the three inside answer.
        var bars = service.bars("NQ", List.of(new long[]{T0 - 60, 60, 5}));
        assertEquals(List.of(T0, T0 + 60, T0 + 120), bars.stream().map(b -> b.volume()[0]).toList());
        // A 2m bar straddling the session end is left to the OHLC approximation.
        assertTrue(service.bars("NQ", List.of(new long[]{T0 + 120, 120, 1})).isEmpty());
        assertTrue(service.bars("ES", List.of(new long[]{T0, 60, 1})).isEmpty());
    }

    @Test void answersOnlyTheNewestSessionsWhenTooManyAreRequested() throws Exception {
        int n = TickProfileService.MAX_SESSIONS + 5;
        var service = new TickProfileService(publishDailySessions(directory, n).toString(), true);
        var bars = service.bars("ES", oneBarPerSession(n));
        assertEquals(TickProfileService.MAX_SESSIONS, bars.size());
        // Sessions 0..4 are dropped; the rest answer in request order with their own volume.
        for (int j = 0; j < bars.size(); j++) {
            int i = j + 5;
            assertArrayEquals(new long[]{T0 + i * 86_400L, 400, i + 1}, bars.get(j).volume());
        }
    }

    @Test void multiSessionRequestsReadEachSessionsOwnRows() throws Exception {
        var service = new TickProfileService(publishDailySessions(directory, 8).toString(), true);
        var bars = service.bars("ES", oneBarPerSession(8));
        assertEquals(8, bars.size());
        for (int i = 0; i < 8; i++) assertArrayEquals(new long[]{T0 + i * 86_400L, 400, i + 1}, bars.get(i).volume());
        // A second request is answered from the cache with the same rows.
        var again = service.bars("ES", oneBarPerSession(8));
        for (int i = 0; i < 8; i++) assertArrayEquals(bars.get(i).volume(), again.get(i).volume());
    }

    @Test void aMissingSessionFileIsUnavailable() throws Exception {
        publishDailySessions(directory, 3);
        Files.delete(directory.resolve("ES/2026-07-06-2.json.gz"));
        var service = new TickProfileService(directory.toString(), true);
        var e = assertThrows(MarketDataException.class,
                () -> service.bars("ES", oneBarPerSession(3)));
        assertEquals("Tick profile session missing", e.getMessage());
    }

    @Test void routesCoverageAndBars() throws Exception {
        mvc.perform(get("/api/volume-profile/coverage").param("symbol", "NQ=F"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tickSize").value(0.25))
                .andExpect(jsonPath("$.sessions[0][0]").value(T0))
                .andExpect(jsonPath("$.sessions[0][1]").value(T0 + 180));
        mvc.perform(get("/api/volume-profile/coverage").param("symbol", "ES=F"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.sessions").isEmpty());
        mvc.perform(get("/api/volume-profile/bars").param("symbol", "NQ=F").param("runs", T0 + ":60:2," + (T0 + 120) + ":60:1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.bars.length()").value(3))
                .andExpect(jsonPath("$.bars[2][1]").value(399))
                .andExpect(jsonPath("$.deltas.length()").value(3))
                .andExpect(jsonPath("$.deltas[2][0]").value(7));
    }

    @Test void aDisabledServiceServesNothingEvenWhenPublished() throws Exception {
        var disabled = new TickProfileService(directory.toString(), false);
        assertTrue(disabled.index("NQ").isEmpty());
        assertTrue(disabled.bars("NQ", List.of(new long[]{T0, 60, 3})).isEmpty());
        var off = MockMvcBuilders.standaloneSetup(new VolumeProfileController(disabled))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
        off.perform(get("/api/volume-profile/coverage").param("symbol", "NQ=F"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.sessions").isEmpty());
        off.perform(get("/api/volume-profile/bars").param("symbol", "NQ=F").param("runs", T0 + ":60:3"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.bars").isEmpty());
    }

    @Test void rejectsBadInput() throws Exception {
        for (String symbol : new String[]{"QQQ", "../NQ=F", "nq=F"})
            mvc.perform(get("/api/volume-profile/coverage").param("symbol", symbol)).andExpect(status().isBadRequest());
        for (String runs : new String[]{"1:60:1", T0 + ":30:1", T0 + ":60:0", "x", T0 + ":60"})
            mvc.perform(get("/api/volume-profile/bars").param("symbol", "NQ=F").param("runs", runs))
                    .andExpect(status().isBadRequest());
    }
}
