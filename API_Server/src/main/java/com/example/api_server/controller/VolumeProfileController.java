package com.example.api_server.controller;

import com.example.api_server.exception.MarketDataException;
import com.example.api_server.service.TickProfileService;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * Exact (trade-print) volume-at-price for futures, so the chart's volume profile can
 * replace its OHLC approximation on bars the published tick data fully covers.
 * The client asks for coverage first, then for the covered bars it holds.
 */
@RestController
@RequestMapping("/api/volume-profile")
public class VolumeProfileController {

    public record Coverage(String symbol, double tickSize, List<long[]> sessions) {}

    /** deltas[i] is bars[i]'s buy-minus-sell volume per tick from its loTick, or null without side data. */
    public record Bars(String symbol, double tickSize, List<long[]> bars, List<long[]> deltas) {}

    private static final Pattern FUTURES = Pattern.compile("([A-Z]{1,4})=F");
    private static final Pattern RUN = Pattern.compile("(\\d{1,12}):(\\d{1,6}):(\\d{1,6})");
    private static final int MAX_RUNS = 2_000;

    private final TickProfileService profiles;

    public VolumeProfileController(TickProfileService profiles) { this.profiles = profiles; }

    /** Published sessions as [start, end) epoch seconds; empty when the symbol has none. */
    @GetMapping("/coverage")
    @RateLimiter(name = "marketDataApi")
    public ResponseEntity<Coverage> coverage(@RequestParam String symbol) {
        var index = profiles.index(product(symbol));
        List<long[]> sessions = index.map(i -> i.sessions().stream()
                .map(s -> new long[]{s.start(), s.end()}).toList()).orElse(List.of());
        return ResponseEntity.ok().cacheControl(CacheControl.maxAge(Duration.ofMinutes(5)))
                .body(new Coverage(symbol, index.map(TickProfileService.Index::tickSize).orElse(0.0), sessions));
    }

    /**
     * {@code runs} is a comma-separated list of {@code start:step:count} (epoch seconds,
     * whole minutes): {@code count} consecutive bars of {@code step} seconds from {@code start}.
     */
    @GetMapping("/bars")
    @RateLimiter(name = "marketDataApi")
    public ResponseEntity<Bars> bars(@RequestParam String symbol, @RequestParam String runs) {
        String product = product(symbol);
        String[] parts = runs.split(",");
        if (parts.length > MAX_RUNS) throw new MarketDataException("Too many runs", 400);
        List<long[]> parsed = new ArrayList<>(parts.length);
        for (String part : parts) {
            Matcher m = RUN.matcher(part);
            if (!m.matches()) throw new MarketDataException("Invalid run: expected start:step:count", 400);
            long start = Long.parseLong(m.group(1)), step = Long.parseLong(m.group(2)), count = Long.parseLong(m.group(3));
            if (start % 60 != 0 || step < 60 || step > 86_400 || step % 60 != 0 || count < 1) {
                throw new MarketDataException("Runs must be whole-minute bars", 400);
            }
            parsed.add(new long[]{start, step, count});
        }
        var index = profiles.index(product);
        var bars = profiles.bars(product, parsed);
        // Sessions never change once published, so a bar's answer is stable.
        return ResponseEntity.ok().cacheControl(CacheControl.maxAge(Duration.ofHours(1)))
                .body(new Bars(symbol, index.map(TickProfileService.Index::tickSize).orElse(0.0),
                        bars.stream().map(TickProfileService.BarProfile::volume).toList(),
                        bars.stream().map(TickProfileService.BarProfile::delta).toList()));
    }

    private static String product(String symbol) {
        Matcher m = FUTURES.matcher(symbol);
        if (!m.matches()) throw new MarketDataException("Tick profiles cover futures symbols only (e.g. NQ=F)", 400);
        return m.group(1);
    }
}
