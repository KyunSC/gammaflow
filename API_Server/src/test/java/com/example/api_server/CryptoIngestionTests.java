package com.example.api_server;

import com.example.api_server.repository.supabase.SupabaseHistoricalDataRepository;
import com.example.api_server.repository.supabase.SupabaseMarketDataRepository;
import com.example.api_server.service.MarketDataIngestionScheduler;
import com.example.api_server.service.MarketDataIngestionService;
import java.time.LocalDateTime;
import java.time.ZonedDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class CryptoIngestionTests {
    @Test void ingestsCryptoBarsAroundTheClockWithoutSnapshots() {
        var service = mock(MarketDataIngestionService.class);
        new MarketDataIngestionScheduler(service, "IWM", "btc-usd, ETH-USD", true).runCrypto();
        verify(service).ingestCryptoIntraday(List.of("BTC-USD", "ETH-USD"));
        verify(service, never()).ingestPrices(anyList(), anyBoolean());
        verify(service, never()).ingestIntraday(anyList(), anyBoolean());
    }

    @Test void cryptoIngestionHonoursTheKillSwitchAndEmptyList() {
        var service = mock(MarketDataIngestionService.class);
        new MarketDataIngestionScheduler(service, "IWM", "BTC-USD", false).runCrypto();
        new MarketDataIngestionScheduler(service, "IWM", "", true).runCrypto();
        verifyNoInteractions(service);
    }

    @Test void cryptoDailyRefreshRunsOnceJustAfterUtcMidnight() {
        assertTrue(MarketDataIngestionScheduler.shouldFetchCryptoDaily(ZonedDateTime.parse("2026-10-14T00:10:00Z")));
        assertFalse(MarketDataIngestionScheduler.shouldFetchCryptoDaily(ZonedDateTime.parse("2026-10-14T00:05:00Z")));
        assertFalse(MarketDataIngestionScheduler.shouldFetchCryptoDaily(ZonedDateTime.parse("2026-10-14T00:15:00Z")));
        assertFalse(MarketDataIngestionScheduler.shouldFetchCryptoDaily(ZonedDateTime.parse("2026-10-14T12:10:00Z")));
    }

    @Test void cryptoIntradayWritesOnlyFromTheNewestStoredBar() {
        // Three bars 2025-01-04T23:58Z, 23:59Z and 2025-01-05T00:00Z; the store already holds 23:59.
        String chart = """
                {"chart":{"result":[{"timestamp":[1736035080,1736035140,1736035200],
                "indicators":{"quote":[{"open":[1,1,1],"high":[1,1,1],"low":[1,1,1],"close":[1,1,1],"volume":[1,1,1]}]}}]}}""";
        var calls = new java.util.ArrayList<String>();
        var client = WebClient.builder().exchangeFunction(request -> {
            calls.add(request.url().getQuery());
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE).body(chart).build());
        }).build();
        var historical = mock(SupabaseHistoricalDataRepository.class);
        when(historical.findMaxDateBySymbolAndIntervalType(anyString(), anyString()))
                .thenReturn(LocalDateTime.parse("2025-01-04T23:59:00"));
        new MarketDataIngestionService(client, mock(SupabaseMarketDataRepository.class), historical)
                .ingestCryptoIntraday(List.of("BTC-USD"));

        assertEquals(List.of("interval=1m&range=5d", "interval=5m&range=5d", "interval=1h&range=5d"), calls);
        for (String interval : List.of("1m", "5m", "1h")) {
            verify(historical).upsertBar(eq("BTC-USD"), eq(LocalDateTime.parse("2025-01-04T23:59:00")), eq(interval),
                    any(), any(), any(), any(), any(), any());
            verify(historical).upsertBar(eq("BTC-USD"), eq(LocalDateTime.parse("2025-01-05T00:00:00")), eq(interval),
                    any(), any(), any(), any(), any(), any());
        }
        verify(historical, never()).upsertBar(any(), eq(LocalDateTime.parse("2025-01-04T23:58:00")), any(),
                any(), any(), any(), any(), any(), any());
    }

    @Test void cryptoIntradayBackfillsEverythingForANewSymbol() {
        String chart = """
                {"chart":{"result":[{"timestamp":[1736035080,1736035140],
                "indicators":{"quote":[{"open":[1,1],"high":[1,1],"low":[1,1],"close":[1,1],"volume":[1,1]}]}}]}}""";
        var client = WebClient.builder().exchangeFunction(request -> Mono.just(ClientResponse.create(HttpStatus.OK)
                .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE).body(chart).build())).build();
        var historical = mock(SupabaseHistoricalDataRepository.class);
        new MarketDataIngestionService(client, mock(SupabaseMarketDataRepository.class), historical)
                .ingestCryptoIntraday(List.of("SOL-USD"));
        verify(historical, times(6)).upsertBar(eq("SOL-USD"), any(), any(), any(), any(), any(), any(), any(), any());
    }
}
