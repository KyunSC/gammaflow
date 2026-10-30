package com.example.api_server.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Optional shared-key gate on /api/**. These routes serve Yahoo prices and GEX
 * built from Yahoo option chains, which can't be redistributed; the public site
 * serves synthetic data and never calls this server. With API_ACCESS_KEY set
 * (the deployed backend), a request needs a matching X-Api-Key header, which the
 * nightly workflow and export_backtest_data.py send from GAMMAFLOW_API_KEY.
 * Unset (local runs), every request passes. /health and / stay open for warm-up pings.
 */
@Component
public class ApiKeyFilter extends OncePerRequestFilter {
    private final byte[] key;

    public ApiKeyFilter(@Value("${app.api.access-key:}") String key) {
        this.key = key.strip().getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return key.length == 0
                || !request.getRequestURI().startsWith("/api/")
                || "OPTIONS".equals(request.getMethod());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String given = request.getHeader("X-Api-Key");
        if (given != null && MessageDigest.isEqual(key, given.getBytes(StandardCharsets.UTF_8))) {
            chain.doFilter(request, response);
            return;
        }
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType("application/json");
        response.getWriter().write("{\"message\":\"API key required\"}");
    }
}
