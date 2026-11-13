package com.example.api_server.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Drives {@link MarketDataIngestionService}.
 *
 * Schedule mirrors the Python Azure timers:
 * <ul>
 *   <li>{@link #runRth()} — every 5 min, 09:00–16:55 ET, Mon–Fri. Replaces
 *       {@code ScheduledDataIngestion} for the tickers in
 *       {@code app.ingestion.tickers}.</li>
 *   <li>{@link #runGlobex()} — every 5 min, 18:00–19:55 ET, Sun. Replaces
 *       {@code ScheduledDataIngestionGlobex}. Only futures get fetched since
 *       equity markets are closed.</li>
 * </ul>
 *
 * The Azure {@code TICKER_LIST} env var should be trimmed to the original
 * set ({@code SPY,QQQ,ES=F,NQ=F,XEQT.TO,^VIX}) so the two writers don't
 * double-write the same rows.
 */
@Component
public class MarketDataIngestionScheduler {

    private static final Logger logger = LoggerFactory.getLogger(MarketDataIngestionScheduler.class);

    /** Equity session in ET — used to gate equity vs futures behavior. */
    private static final ZoneId ET = ZoneId.of("America/New_York");
    private static final LocalTime EQUITY_OPEN = LocalTime.of(9, 30);
    /** 16:15 ET, not 16:00 — gives the final intraday bar 15 min to settle.
     *  Matches Python's {@code should_fetch_intraday()} bound. */
    private static final LocalTime EQUITY_CLOSE_PLUS = LocalTime.of(16, 15);

    private final MarketDataIngestionService service;
    private final List<String> tickers;
    private final boolean enabled;

    public MarketDataIngestionScheduler(
            MarketDataIngestionService service,
            @Value("${app.ingestion.tickers:IWM,RTY=F,DIA,YM=F}") String tickersCsv,
            @Value("${app.scheduler.ingestion.enabled:true}") boolean enabled) {
        this.service = service;
        this.tickers = parseTickers(tickersCsv);
        this.enabled = enabled;
    }

    // Scheduled in New York time, so it follows daylight saving on its own:
    // 09:00–16:55 ET all year. A fixed UTC range stopped at 15:55 ET in winter
    // and missed the close bars and the 16:25–16:40 ET daily refresh.
    @Scheduled(cron = "0 */5 9-16 * * MON-FRI", zone = "America/New_York")
    public void runRth() {
        if (!enabled || tickers.isEmpty()) return;
        boolean isMarketHours = isEquitySession();
        logger.info("Ingestion (RTH) started — tickers={}, isMarketHours={}", tickers, isMarketHours);
        service.ingestPrices(tickers, isMarketHours);
        if (isWeekday() && shouldFetchDaily()) {
            logger.info("Triggering daily-bar refresh (16:25–16:40 ET window)");
            service.ingestDaily(tickers);
        }
        if (isWeekday()) {
            service.ingestIntraday(tickers, isMarketHours);
        }
        logger.info("Ingestion (RTH) completed");
    }

    // 18:00–19:55 ET: the first two hours after the Sunday Globex open.
    @Scheduled(cron = "0 */5 18,19 * * SUN", zone = "America/New_York")
    public void runGlobex() {
        if (!enabled || tickers.isEmpty()) return;
        // Futures-only on Sunday Globex: ingestPrices/Intraday skip non-=F
        // when isMarketHours=false.
        logger.info("Ingestion (Globex) started — tickers={}", tickers);
        service.ingestPrices(tickers, false);
        service.ingestIntraday(tickers, false);
        logger.info("Ingestion (Globex) completed");
    }

    private static boolean isWeekday() {
        int dow = ZonedDateTime.now(ET).getDayOfWeek().getValue();
        return dow <= 5;
    }

    private static boolean isEquitySession() {
        ZonedDateTime nowEt = ZonedDateTime.now(ET);
        if (nowEt.getDayOfWeek().getValue() >= 6) return false;
        LocalTime t = nowEt.toLocalTime();
        return !t.isBefore(EQUITY_OPEN) && !t.isAfter(EQUITY_CLOSE_PLUS);
    }

    /**
     * Returns true during the 16:25–16:40 ET window. Mirrors Python's
     * {@code should_fetch_historical()} — the ET-zoned cron ticks at 16:25–16:40
     * in both EDT and EST.
     */
    private static boolean shouldFetchDaily() {
        ZonedDateTime nowEt = ZonedDateTime.now(ET);
        return nowEt.getHour() == 16 && nowEt.getMinute() >= 25 && nowEt.getMinute() <= 40;
    }

    private static List<String> parseTickers(String csv) {
        if (csv == null || csv.isBlank()) return List.of();
        List<String> out = new ArrayList<>();
        for (String s : Arrays.asList(csv.split(","))) {
            String trimmed = s.trim().toUpperCase();
            if (!trimmed.isEmpty()) out.add(trimmed);
        }
        return out;
    }
}
