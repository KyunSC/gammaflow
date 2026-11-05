package com.example.api_server.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Optional shared-key gate on /api/**. These routes serve Yahoo prices and GEX
 * built from Yahoo option chains, which can't be redistributed; the public site
 * serves synthetic data and never calls this server. With API_ACCESS_KEY set
 * (the deployed backend), a request needs a matching X-Api-Key header, which the
 * nightly workflow and export_backtest_data.py send from GAMMAFLOW_API_KEY.
 * Unset (local runs), every request passes. /health and / stay open for warm-up pings;
 * with a key set, everything else is denied by default, not only paths under /api.
 */
@Component
public class ApiKeyFilter extends OncePerRequestFilter {
    private static final Set<String> PUBLIC_PATHS = Set.of("/", "/health");

    private final byte[] key;

    public ApiKeyFilter(@Value("${app.api.access-key:}") String key) {
        this.key = key.strip().getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return key.length == 0
                || PUBLIC_PATHS.contains(normalizedPath(request))
                || "OPTIONS".equals(request.getMethod());
    }

    // Decoded, with path parameters and dot segments removed by the container. getRequestURI()
    // is raw, so /api;x=1/... and /%61pi/... don't look like the /api routes they reach.
    private static String normalizedPath(HttpServletRequest request) {
        String pathInfo = request.getPathInfo();
        return pathInfo == null ? request.getServletPath() : request.getServletPath() + pathInfo;
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
