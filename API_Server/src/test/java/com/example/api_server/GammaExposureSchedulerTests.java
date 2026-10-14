package com.example.api_server;

import com.example.api_server.entity.GammaExposureEntity;
import com.example.api_server.repository.supabase.SupabaseGammaExposureRepository;
import com.example.api_server.service.GammaExposureComputeService;
import com.example.api_server.service.GammaExposureComputeService.GexResult;
import com.example.api_server.service.GammaExposureScheduler;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.cache.concurrent.ConcurrentMapCacheManager;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.support.CronExpression;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class GammaExposureSchedulerTests {
    static final ZoneId ET = ZoneId.of("America/New_York");

    static Scheduled postclose() throws Exception {
        return GammaExposureScheduler.class.getMethod("runPostclose").getAnnotation(Scheduled.class);
    }

    static ZonedDateTime nextFire(Scheduled s, ZonedDateTime from) {
        return CronExpression.parse(s.cron()).next(from.withZoneSameInstant(ZoneId.of(s.zone())));
    }

    @Test void postcloseFiresAt1610EtInBothEdtAndEst() throws Exception {
        Scheduled s = postclose();
        // Thu 2026-09-24 (EDT, the missing day) and Thu 2026-12-03 (EST).
        for (LocalDateTime day : List.of(LocalDateTime.of(2026, 9, 24, 15, 0), LocalDateTime.of(2026, 12, 3, 15, 0))) {
            ZonedDateTime fire = nextFire(s, day.atZone(ET)).withZoneSameInstant(ET);
            assertEquals(day.toLocalDate(), fire.toLocalDate());
            assertEquals(16, fire.getHour());
            assertEquals(10, fire.getMinute());
        }
    }

    @Test void postcloseSkipsWeekends() throws Exception {
        // Fri 2026-09-25 17:00 ET → next fire is Mon 2026-09-28 16:10 ET.
        ZonedDateTime fire = nextFire(postclose(), ZonedDateTime.of(2026, 9, 25, 17, 0, 0, 0, ET)).withZoneSameInstant(ET);
        assertEquals(ZonedDateTime.of(2026, 9, 28, 16, 10, 0, 0, ET), fire);
    }

    @Test void postclosePersistsEveryPairWithoutTheMarketOpenGate() {
        GammaExposureComputeService compute = mock(GammaExposureComputeService.class);
        SupabaseGammaExposureRepository repo = mock(SupabaseGammaExposureRepository.class);
        when(compute.fetchAndCompute(any())).thenAnswer(inv -> result(inv.getArgument(0)));

        new GammaExposureScheduler(compute, repo, new ConcurrentMapCacheManager("gammaExposure"), true).runPostclose();

        for (String symbol : GammaExposureComputeService.GEX_PAIRS.keySet()) verify(compute).fetchAndCompute(symbol);
        verify(repo, times(GammaExposureComputeService.GEX_PAIRS.size())).save(any(GammaExposureEntity.class));
    }

    @Test void postcloseRespectsTheKillSwitch() {
        GammaExposureComputeService compute = mock(GammaExposureComputeService.class);
        SupabaseGammaExposureRepository repo = mock(SupabaseGammaExposureRepository.class);

        new GammaExposureScheduler(compute, repo, new ConcurrentMapCacheManager(), false).runPostclose();

        verifyNoInteractions(compute, repo);
    }

    static GexResult result(String etf) {
        return new GexResult(etf, GammaExposureComputeService.GEX_PAIRS.get(etf), 500, 20000, 40,
                List.of("2026-09-24"), false, null, null, null, null, List.of());
    }
}
