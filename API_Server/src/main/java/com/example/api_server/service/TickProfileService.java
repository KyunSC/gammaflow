package com.example.api_server.service;

import com.example.api_server.exception.MarketDataException;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import jakarta.annotation.PreDestroy;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.GZIPInputStream;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * Exact volume-at-price from futures trade prints, published per RTH session by
 * functions/ml/publish_tick_profiles.py. Location is a local folder or an https
 * prefix (a container SAS query string is kept at the end of each file URL).
 * Session files are immutable, so they are cached until evicted; the index is
 * re-read every few minutes so newly published sessions show up. The prints are
 * licensed data, so the service answers nothing unless tickprofile.enabled is set
 * (local runs only; production never serves them).
 */
@Service
public class TickProfileService {

    public record Session(long start, long end, String file) {}

    public record Index(double tickSize, List<Session> sessions) {}

    /**
     * One session's per-minute prints: minute i has volumes[i][k] contracts at tick lo[i] + k,
     * of which buyers lifted deltas[i][k] more than sellers hit. deltas is null for sessions
     * published without aggressor side.
     */
    record Day(long[] minutes, long[] lo, int[][] volumes, int[][] deltas) {}

    /** One bar: {barStart, loTick, volume at loTick, ...}, and delta per tick from loTick (or null). */
    public record BarProfile(long[] volume, long[] delta) {}

    private static final long MAX_BARS = 50_000;
    /** Sessions answered per request (the newest); bars in older ones are left to the caller. */
    public static final int MAX_SESSIONS = 120;

    private final boolean enabled;
    private final String base;
    private final String query;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    private final JsonMapper json = JsonMapper.builder().build();
    private final Cache<String, Optional<Index>> indexes = Caffeine.newBuilder()
            .expireAfterWrite(Duration.ofMinutes(10)).maximumSize(20).build();
    private final Cache<String, Day> days = Caffeine.newBuilder()
            .expireAfterAccess(Duration.ofHours(6)).maximumSize(200).build();
    private final ExecutorService loader = Executors.newFixedThreadPool(6);

    public TickProfileService(@Value("${tickprofile.location:./tick-profiles}") String location,
                              @Value("${tickprofile.enabled:false}") boolean enabled) {
        this.enabled = enabled;
        int q = location.indexOf('?');
        this.base = (q < 0 ? location : location.substring(0, q)).replaceAll("/+$", "");
        this.query = q < 0 ? "" : location.substring(q);
    }

    @PreDestroy
    void shutdown() {
        loader.shutdownNow();
    }

    /** Published sessions for a futures root (e.g. "NQ"), or empty when none are published or disabled. */
    public Optional<Index> index(String product) {
        if (!enabled) return Optional.empty();
        return indexes.get(product, p -> read(p + "/index.json").map(this::parseIndex));
    }

    /**
     * Per-bar volume-at-price for runs of equal-width bars, each {start, step, count}
     * in epoch seconds. A bar is answered only if it lies entirely inside one published
     * session, and only in the newest MAX_SESSIONS sessions touched; others are left
     * for the caller to approximate.
     */
    public List<BarProfile> bars(String product, List<long[]> runs) {
        Index index = index(product).orElse(null);
        if (index == null) return List.of();
        long total = runs.stream().mapToLong(r -> r[2]).sum();
        if (total > MAX_BARS) throw new MarketDataException("Too many bars requested", 400);

        Set<Session> touched = new LinkedHashSet<>();
        for (long[] run : runs) {
            for (long k = 0; k < run[2]; k++) {
                long start = run[0] + k * run[1];
                Session session = containing(index.sessions(), start, start + run[1]);
                if (session != null) touched.add(session);
            }
        }
        List<String> keys = touched.stream()
                .sorted(Comparator.comparingLong(Session::start).reversed())
                .limit(MAX_SESSIONS)
                .map(s -> product + "/" + s.file())
                .toList();
        // Held for the whole request, so an eviction mid-request can't force a reload.
        Map<String, Day> loaded = days.getAll(keys, this::loadDays);

        List<BarProfile> out = new ArrayList<>();
        for (long[] run : runs) {
            for (long k = 0; k < run[2]; k++) {
                long start = run[0] + k * run[1];
                long end = start + run[1];
                Session session = containing(index.sessions(), start, end);
                if (session == null) continue;
                Day day = loaded.get(product + "/" + session.file());
                if (day == null) continue;
                BarProfile row = sum(day, start, end);
                if (row != null) out.add(row);
            }
        }
        return out;
    }

    private static Session containing(List<Session> sessions, long start, long end) {
        int lo = 0, hi = sessions.size() - 1;
        while (lo <= hi) {
            int mid = (lo + hi) >>> 1;
            Session s = sessions.get(mid);
            if (s.end() <= start) lo = mid + 1;
            else if (s.start() > start) hi = mid - 1;
            else return end <= s.end() ? s : null;
        }
        return null;
    }

    private static BarProfile sum(Day day, long start, long end) {
        int from = lowerBound(day.minutes(), start);
        int to = lowerBound(day.minutes(), end);
        if (from >= to) return null;
        long lo = Long.MAX_VALUE, hi = Long.MIN_VALUE;
        for (int i = from; i < to; i++) {
            lo = Math.min(lo, day.lo()[i]);
            hi = Math.max(hi, day.lo()[i] + day.volumes()[i].length - 1);
        }
        long[] row = new long[(int) (hi - lo) + 3];
        row[0] = start;
        row[1] = lo;
        long[] delta = day.deltas() == null ? null : new long[row.length - 2];
        for (int i = from; i < to; i++) {
            int offset = (int) (day.lo()[i] - lo);
            int[] v = day.volumes()[i];
            for (int k = 0; k < v.length; k++) row[offset + k + 2] += v[k];
            if (delta != null) {
                int[] d = day.deltas()[i];
                for (int k = 0; k < d.length; k++) delta[offset + k] += d[k];
            }
        }
        return new BarProfile(row, delta);
    }

    private static int lowerBound(long[] sorted, long key) {
        int i = Arrays.binarySearch(sorted, key);
        return i >= 0 ? i : -i - 1;
    }

    /** Reads the sessions missing from the cache in parallel. */
    private Map<String, Day> loadDays(Set<? extends String> keys) {
        Map<String, CompletableFuture<Day>> pending = new LinkedHashMap<>();
        for (String key : keys) {
            pending.put(key, CompletableFuture.supplyAsync(() -> read(key)
                    .map(this::parseDay)
                    .orElseThrow(() -> new MarketDataException("Tick profile session missing", 503)), loader));
        }
        Map<String, Day> out = new HashMap<>();
        for (var entry : pending.entrySet()) {
            try {
                out.put(entry.getKey(), entry.getValue().join());
            } catch (CompletionException e) {
                pending.values().forEach(f -> f.cancel(true));
                if (e.getCause() instanceof RuntimeException cause) throw cause;
                throw e;
            }
        }
        return out;
    }

    private Index parseIndex(JsonNode root) {
        List<Session> sessions = new ArrayList<>();
        for (JsonNode s : root.get("sessions")) {
            String file = s.get("file").asString();
            if (!file.matches("[0-9-]+\\.json(\\.gz)?")) throw new MarketDataException("Invalid tick profile index", 503);
            sessions.add(new Session(s.get("start").asLong(), s.get("end").asLong(), file));
        }
        sessions.sort((a, b) -> Long.compare(a.start(), b.start()));
        return new Index(root.get("tickSize").asDouble(), List.copyOf(sessions));
    }

    private Day parseDay(JsonNode root) {
        JsonNode minutes = root.get("minutes");
        int n = minutes.size();
        long[] t = new long[n];
        long[] lo = new long[n];
        int[][] volumes = new int[n][];
        for (int i = 0; i < n; i++) {
            JsonNode m = minutes.get(i);
            t[i] = m.get(0).asLong();
            lo[i] = m.get(1).asLong();
            volumes[i] = new int[m.size() - 2];
            for (int k = 0; k < volumes[i].length; k++) volumes[i][k] = m.get(k + 2).asInt();
        }
        JsonNode delta = root.get("delta");
        if (delta == null || delta.isNull()) return new Day(t, lo, volumes, null);
        if (delta.size() != n) throw new MarketDataException("Invalid tick profile session", 503);
        int[][] deltas = new int[n][];
        for (int i = 0; i < n; i++) {
            JsonNode d = delta.get(i);
            if (d.size() != volumes[i].length) throw new MarketDataException("Invalid tick profile session", 503);
            deltas[i] = new int[d.size()];
            for (int k = 0; k < deltas[i].length; k++) deltas[i][k] = d.get(k).asInt();
        }
        return new Day(t, lo, volumes, deltas);
    }

    private Optional<JsonNode> read(String relative) {
        try {
            byte[] body;
            if (base.startsWith("https://")) {
                var request = HttpRequest.newBuilder(URI.create(base + "/" + relative + query))
                        .timeout(Duration.ofSeconds(30)).GET().build();
                var result = client.send(request, HttpResponse.BodyHandlers.ofByteArray());
                if (result.statusCode() == 404) return Optional.empty();
                if (result.statusCode() != 200) throw new IOException("HTTP " + result.statusCode());
                body = result.body();
            } else {
                body = Files.readAllBytes(Path.of(base).resolve(relative));
            }
            if (relative.endsWith(".gz")) {
                try (var in = new GZIPInputStream(new ByteArrayInputStream(body))) { body = in.readAllBytes(); }
            }
            return Optional.of(json.readTree(body));
        } catch (NoSuchFileException e) {
            return Optional.empty();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new MarketDataException("Tick profile request interrupted", 503);
        } catch (IOException | RuntimeException e) {
            throw new MarketDataException("Tick profile storage unavailable", 503);
        }
    }
}
