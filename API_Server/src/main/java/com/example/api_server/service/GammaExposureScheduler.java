package com.example.api_server.service;

import com.example.api_server.entity.GammaExposureEntity;
import com.example.api_server.entity.GammaLevelEntity;
import com.example.api_server.repository.supabase.SupabaseGammaExposureRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.CacheManager;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;

/**
 * Replaces the Python ScheduledGammaExposure Azure Function.
 *
 * Runs every 5 minutes during RTH (13:00–20:59 UTC, weekdays). The Python
 * function used the same cron expression — the only change is *where* it
 * runs (Render free tier vs Azure paid execution).
 *
 * The instance is kept warm by UptimeRobot pinging /health during market
 * hours, so the scheduler reliably fires (per the hosting note in CLAUDE.md).
 *
 * Also takes the one post-close snapshot at 16:10 ET that the Python
 * ScheduledGammaExposurePostclose function used to take: by then the
 * 10-min-delayed Yahoo feed has caught up to the 16:00 ET settlement. The
 * cron is pinned to America/New_York, so unlike the Python dual-UTC cron it
 * needs no DST window check.
 */
@Component
public class GammaExposureScheduler {

    private static final Logger logger = LoggerFactory.getLogger(GammaExposureScheduler.class);

    private final GammaExposureComputeService computeService;
    private final SupabaseGammaExposureRepository repository;
    private final CacheManager cacheManager;
    private final boolean enabled;

    public GammaExposureScheduler(GammaExposureComputeService computeService,
                                  SupabaseGammaExposureRepository repository,
                                  CacheManager cacheManager,
                                  @Value("${app.scheduler.gex.enabled:true}") boolean enabled) {
        this.computeService = computeService;
        this.repository = repository;
        this.cacheManager = cacheManager;
        this.enabled = enabled;
    }

    @Scheduled(cron = "0 */5 13-20 * * MON-FRI", zone = "UTC")
    public void run() {
        if (!enabled) {
            return;
        }
        if (!GammaExposureComputeService.isMarketOpen()) {
            logger.info("Equity market closed — skipping GEX computation.");
            return;
        }

        logger.info("ScheduledGammaExposure started");
        computeAll();
        logger.info("ScheduledGammaExposure completed");
    }

    @Scheduled(cron = "0 10 16 * * MON-FRI", zone = "America/New_York")
    public void runPostclose() {
        if (!enabled) {
            return;
        }
        // Deliberately not gated on isMarketOpen(): that is false after 16:00
        // ET, which is why the regular cadence never covered this snapshot.
        logger.info("ScheduledGammaExposurePostclose started");
        computeAll();
        logger.info("ScheduledGammaExposurePostclose completed");
    }

    private void computeAll() {
        for (String etfSymbol : GammaExposureComputeService.GEX_PAIRS.keySet()) {
            try {
                GammaExposureComputeService.GexResult result = computeService.fetchAndCompute(etfSymbol);
                Long id = persist(result);
                evictCache(etfSymbol);
                logger.info("Saved GEX data (id={}), {}={}, {}={}, {} levels",
                        id, etfSymbol, result.etfPrice(),
                        result.futuresSymbol(), result.futuresPrice(),
                        result.levels().size());
            } catch (Exception ex) {
                // Per-symbol isolation: one bad pair can't kill the others.
                // The API already serves the latest valid row from DB via
                // findLatestValidBySymbol, so a missed cycle is invisible to
                // the chart.
                logger.error("Error computing gamma exposure for {}: {}", etfSymbol, ex.getMessage(), ex);
            }
        }
    }

    @Transactional("supabaseTransactionManager")
    public Long persist(GammaExposureComputeService.GexResult result) {
        GammaExposureEntity exposure = new GammaExposureEntity();
        exposure.setSymbol(result.etfSymbol());
        exposure.setComputedAt(LocalDateTime.now(ZoneOffset.UTC));
        exposure.setEtfPrice(result.etfPrice());
        exposure.setFuturesPrice(result.futuresPrice());
        exposure.setConversionRatio(result.conversionRatio());
        exposure.setExpirationsUsed(String.join(",", result.expirationsUsed()));
        exposure.setMarketOpen(result.marketOpen());
        exposure.setPcrVolume(result.pcrVolume());
        exposure.setPcrOi(result.pcrOi());
        exposure.setIvAtm(result.ivAtm());
        exposure.setIvSkew(result.ivSkew());

        List<GammaLevelEntity> levels = new ArrayList<>(result.levels().size());
        for (GammaExposureComputeService.StrikeData s : result.levels()) {
            GammaLevelEntity lvl = new GammaLevelEntity();
            lvl.setGammaExposure(exposure);
            lvl.setStrikeEtf(s.strikeEtf());
            lvl.setStrikeFutures(s.strikeFutures());
            lvl.setGex(s.gex());
            lvl.setGexCall(s.gexCall());
            lvl.setGexPut(s.gexPut());
            lvl.setGex0dte(s.gex0dte());
            lvl.setGex1dte(s.gex1dte());
            lvl.setGexWeekly(s.gexWeekly());
            lvl.setGexMonthly(s.gexMonthly());
            lvl.setLabel(s.label());
            levels.add(lvl);
        }
        exposure.setLevels(levels);

        repository.save(exposure);
        return exposure.getId();
    }

    private void evictCache(String etfSymbol) {
        // GammaExposureService is @Cacheable on uppercase symbol — the cron
        // freshens the DB row, evicting forces the next read to surface it
        // instead of serving a stale 5-min entry.
        var cache = cacheManager.getCache("gammaExposure");
        if (cache != null) cache.evict(etfSymbol.toUpperCase());
    }
}
