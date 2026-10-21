/**
 * ============================================
 * PORTFOLIO MAIN JAVASCRIPT
 * ============================================
 * Handles: Grid generation, filtering, lightbox, hover previews
 * Supports: YouTube, Instagram, TikTok
 */

(function() {
    'use strict';

    // ============================================
    // DOM Elements
    // ============================================
    const lightbox = document.getElementById('lightbox');
    const lightboxClose = document.getElementById('lightbox-close');
    const videoContainer = document.getElementById('video-container');


    // ============================================
    // View Counter (live odometer ticker)
    // ============================================
    // Runs entirely client-side. No API calls, no backend.
    // Starts at (totalYouTubeViews - VIEW_TICKS_PER_LOOP), ticks +1 every
    // VIEW_TICK_INTERVAL_MS, and on reaching the real total snaps back and loops.
    // 150 ticks * 2000ms = 300s = 5 minutes per loop.
    //
    // Each digit lives in its own "slot" (overflow:hidden, height:1em) containing
    // a vertical strip of <span>0</span>...<span>9</span>. To show digit N we
    // translate the strip up by N em. Only digits whose value actually changed
    // animate, so the rightmost digit rolls every tick and higher digits roll
    // less often — exactly like a real odometer.

    const VIEW_TICK_INTERVAL_MS = 2000;
    const VIEW_TICKS_PER_LOOP = 150;

    function formatTotalViews(num) {
        return num.toLocaleString('en-US');
    }

    function updateViewCounter() {
        const counter = document.getElementById('view-counter');
        if (!counter || typeof totalYouTubeViews === 'undefined' || totalYouTubeViews <= 0) return;

        const realTotal = totalYouTubeViews;
        const startValue = realTotal - VIEW_TICKS_PER_LOOP;

        const stat = document.createElement('div');
        stat.className = 'hero-stat-count';
        stat.innerHTML = '<span class="hero-stat-number odometer"></span><span class="hero-stat-label">views on<br>edited videos</span>';
        counter.insertBefore(stat, counter.firstChild);

        // Static video count to the LEFT of the views odometer.
        // We don't animate this — Daniel doesn't edit a video every second.
        // Counts every source sheet (YouTube long-form + Shorts, Instagram, TikTok);
        // a cross-posted edit counts once per platform, hence "published" not "edited".
        // Falls back to the YouTube-only count for an older projects.js without totalVideos.
        const publishedCount = (typeof totalVideos !== 'undefined' && totalVideos > 0)
            ? totalVideos
            : (typeof totalYouTubeVideos !== 'undefined' ? totalYouTubeVideos : 0);
        if (publishedCount > 0) {
            const videosStat = document.createElement('div');
            videosStat.className = 'hero-stat-count hero-stat-count--secondary';
            videosStat.innerHTML =
                '<span class="hero-stat-number">' + publishedCount.toLocaleString('en-US') + '</span>' +
                '<span class="hero-stat-label">published<br>videos</span>';
            counter.insertBefore(videosStat, stat);
        }

        const numberEl = stat.querySelector('.hero-stat-number');

        // Build the odometer DOM from the start value's formatted string.
        // Digit count is fixed at init; the value never crosses a power of 10.
        const initialFormatted = formatTotalViews(startValue);
        const slots = []; // { strip, currentDigit }

        for (let i = 0; i < initialFormatted.length; i++) {
            const ch = initialFormatted.charAt(i);
            if (ch >= '0' && ch <= '9') {
                const slot = document.createElement('span');
                slot.className = 'odometer-digit';
                const strip = document.createElement('span');
                strip.className = 'odometer-strip';
                // 11 children: 0..9 plus a duplicate 0 at the bottom so a
                // 9 -> 0 transition can roll FORWARD into the duplicate 0
                // and then silently snap back to the top 0 for the next tick.
                for (let d = 0; d <= 10; d++) {
                    const dEl = document.createElement('span');
                    dEl.className = 'odometer-d';
                    dEl.textContent = String(d % 10);
                    strip.appendChild(dEl);
                }
                slot.appendChild(strip);
                numberEl.appendChild(slot);
                const initDigit = parseInt(ch, 10);
                strip.style.transform = 'translateY(-' + initDigit + 'em)';
                slots.push({ strip: strip, currentDigit: initDigit, snapBackTimer: null });
            } else {
                const sep = document.createElement('span');
                sep.className = 'odometer-sep';
                sep.textContent = ch;
                numberEl.appendChild(sep);
            }
        }

        let current = startValue;
        let intervalId = null;

        function tick() {
            current += 1;
            let isReset = false;
            if (current > realTotal) {
                current = startValue;
                isReset = true;
            }
            setOdometer(slots, formatTotalViews(current), !isReset);
        }

        function start() {
            if (intervalId === null) {
                intervalId = setInterval(tick, VIEW_TICK_INTERVAL_MS);
            }
        }

        function stop() {
            if (intervalId !== null) {
                clearInterval(intervalId);
                intervalId = null;
            }
        }

        start();

        // Pause when tab is hidden so we don't burn battery in the background.
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                stop();
            } else {
                start();
            }
        });
    }

    /**
     * Update the odometer slots to show the given formatted string.
     * Only digits whose value changed will move. If `animate` is false,
     * the change snaps without transition (used for the loop reset).
     *
     * Rollover handling: when a digit goes 9 -> 0 we animate forward to
     * the duplicate 0 at position 10, then schedule a silent snap-back
     * to position 0 once the transition has finished.
     */
    function setOdometer(slots, formatted, animate) {
        let slotIdx = 0;
        for (let i = 0; i < formatted.length; i++) {
            const ch = formatted.charAt(i);
            if (ch < '0' || ch > '9') continue;
            const newDigit = parseInt(ch, 10);
            const slot = slots[slotIdx++];
            if (!slot) break;
            if (slot.currentDigit === newDigit) continue;
            const strip = slot.strip;

            // Cancel any pending snap-back from a previous rollover so we
            // don't clobber a freshly-set transform.
            if (slot.snapBackTimer !== null) {
                clearTimeout(slot.snapBackTimer);
                slot.snapBackTimer = null;
            }

            const isRollover = slot.currentDigit === 9 && newDigit === 0;

            if (!animate) {
                // Reset path: snap immediately, no transition.
                strip.style.transition = 'none';
                strip.style.transform = 'translateY(-' + newDigit + 'em)';
                void strip.offsetHeight;
                strip.style.transition = '';
            } else if (isRollover) {
                // Roll forward into the duplicate 0 at position 10, then
                // snap back to position 0 once the roll has finished.
                strip.style.transform = 'translateY(-10em)';
                slot.snapBackTimer = setTimeout(function() {
                    slot.snapBackTimer = null;
                    // Defensive: only snap if no later change has happened.
                    if (slot.currentDigit === 0) {
                        strip.style.transition = 'none';
                        strip.style.transform = 'translateY(0em)';
                        void strip.offsetHeight;
                        strip.style.transition = '';
                    }
                }, 650);
            } else {
                strip.style.transform = 'translateY(-' + newDigit + 'em)';
            }
            slot.currentDigit = newDigit;
        }
    }

    // ============================================
    // Helper Functions
    // ============================================

    /**
     * Get thumbnail URL based on platform
     */
    function getThumbnailUrl(project) {
        const videoId = project.videoId || project.youtubeId;
        const platform = project.platform || 'youtube';

        // For Instagram/TikTok, use local thumbnail
        if (platform === 'instagram' || platform === 'tiktok') {
            return `images/thumbnails/${videoId}.jpg`;
        }

        // YouTube: use their CDN
        return `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
    }

    /**
     * Get fallback thumbnail URL (lower quality)
     */
    function getFallbackThumbnail(project) {
        const videoId = project.videoId || project.youtubeId;
        if (project.platform === 'youtube' || !project.platform) {
            return `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
        }
        return '';
    }

    /**
     * Get YouTube embed URL for lightbox (with sound)
     */
    function getYouTubeEmbedUrl(videoId) {
        return `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0&vq=hd1080`;
    }

    /**
     * Get YouTube embed URL for hover preview (muted, no controls)
     */
    function getYouTubePreviewUrl(videoId) {
        return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=1&controls=0&showinfo=0&rel=0&loop=1&playlist=${videoId}&modestbranding=1&playsinline=1&enablejsapi=1`;
    }

    /**
     * Check if project has a local preview video available
     */
    function hasLocalPreview(project) {
        return !!project.previewVideo;
    }

    /**
     * Escape a value for use inside a double-quoted HTML attribute.
     */
    function escapeAttr(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    /**
     * <track> markup for a project's subtitle file (project.subtitles), or ''.
     * Same-origin .vtt, so no crossorigin attribute is needed on the <video>.
     */
    function trackHTML(project) {
        if (!project || !project.subtitles) return '';
        const lang = project.subtitlesLang || 'en';
        const label = project.subtitlesLabel || 'Subtitles';
        return `<track kind="subtitles" src="${escapeAttr(project.subtitles)}" srclang="${escapeAttr(lang)}" label="${escapeAttr(label)}" default>`;
    }

    // ============================================
    // Grid Generation
    // ============================================

    /**
     * Create a single grid item element
     */
    function createGridItem(project, opts) {
        opts = opts || {};
        // In showcase contexts (the Featured hero tile + its shorts) we never want
        // the bare YouTube embed on hover — its player chrome ("More videos", logo,
        // pause button) looks bad blown up. Use the local clip if there is one, else
        // just keep the static thumbnail.
        const allowIframePreview = !opts.noIframePreview;
        const item = document.createElement('div');
        const videoId = project.videoId || project.youtubeId;
        const platform = project.platform || 'youtube';
        const canUseIframePreview = platform === 'youtube' && allowIframePreview;
        const canPreview = hasLocalPreview(project) || canUseIframePreview;
        const isVertical = platform === 'instagram' || platform === 'tiktok';

        item.className = 'grid-item' + (canPreview ? ' has-preview' : '') + (isVertical ? ' vertical-item' : '');
        item.dataset.category = project.category;
        item.dataset.videoId = videoId;
        item.dataset.platform = platform;

        const thumbnailUrl = getThumbnailUrl(project);
        const fallbackUrl = getFallbackThumbnail(project);
        // "EN subtitles" pill on the thumb when the lightbox will carry a subtitle track.
        const subsBadge = project.subtitles
            ? `<span class="subs-badge" aria-label="${escapeAttr(project.subtitlesLabel || 'Subtitles')} subtitles">${escapeAttr(project.subtitlesLang || 'cc')} subtitles</span>`
            : '';

        item.innerHTML = `
            <div class="grid-item-thumb">
                <img src="${thumbnailUrl}" alt="${project.title}" loading="lazy"
                     ${fallbackUrl ? `onerror="this.src='${fallbackUrl}'"` : ''}>
                <div class="grid-item-preview"></div>
            </div>
            <div class="grid-item-overlay">
                <h3 class="grid-item-title">${project.title}</h3>
                <span class="grid-item-meta">${project.channelName || ''} ${project.channelName && project.viewCount ? '·' : ''} ${project.viewCount || ''}</span>
            </div>
            ${subsBadge}
        `;

        // Click handler - Open appropriate lightbox based on platform.
        // A self-hosted copy (project.videoSrc) always wins: it exists because the
        // video needs our own player (subtitle track). A YouTube short with a local
        // mp4 (project.localSource) goes through the local-video lightbox so the
        // 9:16 video fills a tall vertical container instead of getting
        // pillarboxed inside YouTube's 16:9 embed chrome.
        item.addEventListener('click', () => {
            if (project.videoSrc) {
                openHostedLightbox(project);
            } else if (platform === 'youtube') {
                if (project.localSource && project.category === 'short-form') {
                    openVideoLightbox(videoId, 'youtube', project.url, project);
                } else {
                    openYouTubeLightbox(videoId, project.url);
                }
            } else if (platform === 'instagram') {
                openVideoLightbox(videoId, 'instagram', project.url, project);
            } else if (platform === 'tiktok') {
                openVideoLightbox(videoId, 'tiktok', project.url, project);
            }
        });

        // Hover preview handlers (desktop only)
        let hoverTimeout;
        let isHovering = false;
        const previewContainer = item.querySelector('.grid-item-preview');

        function showIframePreview() {
            const previewUrl = getYouTubePreviewUrl(videoId);
            previewContainer.innerHTML = `<iframe src="${previewUrl}" title="Video preview" allow="autoplay; encrypted-media" loading="lazy"></iframe>`;
            item.classList.add('preview-active');
        }

        item.addEventListener('mouseenter', () => {
            if (!canPreview) return;
            isHovering = true;

            // Delay before loading preview (like YouTube)
            hoverTimeout = setTimeout(() => {
                if (!isHovering) return;
                if (hasLocalPreview(project)) {
                    // Use the local clip. Only reveal it (preview-active) once a frame
                    // is decoded so we never flash a black box; if the clip is missing
                    // or unplayable, fall back to the iframe (when allowed) or just
                    // leave the thumbnail. All async callbacks bail if the mouse left.
                    const video = document.createElement('video');
                    video.muted = true;
                    video.loop = true;
                    video.playsInline = true;
                    video.preload = 'auto';
                    video.addEventListener('loadeddata', () => {
                        if (!isHovering || !previewContainer.contains(video)) return;
                        item.classList.add('preview-active');
                        video.play().catch(() => {});
                    });
                    video.addEventListener('error', () => {
                        if (!isHovering || !previewContainer.contains(video)) return;
                        previewContainer.innerHTML = '';
                        item.classList.remove('preview-active');
                        if (canUseIframePreview) showIframePreview();
                    });
                    video.src = project.previewVideo;
                    previewContainer.appendChild(video);
                } else if (canUseIframePreview) {
                    showIframePreview();
                }
            }, 500);
        });

        item.addEventListener('mouseleave', () => {
            isHovering = false;
            clearTimeout(hoverTimeout);
            item.classList.remove('preview-active');
            // Clean up video to release memory
            const video = previewContainer.querySelector('video');
            if (video) {
                video.pause();
                video.src = '';
                video.load();
            }
            previewContainer.innerHTML = '';
        });

        return item;
    }

    /**
     * Render every section from the `sections` global in projects.js, in
     * order. Layouts: "hero" (rows of one optional long-form plus its shorts),
     * "wide" (16:9 grid), "tall" (9:16 grid). Titles are free text chosen in
     * the editor. How a video plays is decided per item (platform, category,
     * localSource), never by the section it sits in, so sections can be
     * renamed or re-laid-out freely. Empty sections stay off the page.
     */
    function renderSections() {
        const root = document.getElementById('sections-root');
        if (!root) return;
        root.innerHTML = '';
        const list = (typeof sections !== 'undefined' && Array.isArray(sections)) ? sections : [];
        list.forEach(section => {
            const count = section.layout === 'hero'
                ? (section.groups || []).reduce((n, g) => n + (g.items || []).length, 0)
                : (section.items || []).length;
            if (!count) return;

            const el = document.createElement('section');
            el.className = 'section' + (section.layout === 'hero' ? ' featured-section' : '');
            el.id = 'section-' + section.id;
            el.dataset.layout = section.layout;

            const title = document.createElement('h2');
            title.className = 'section-title';
            title.textContent = section.title || '';
            el.appendChild(title);

            if (section.layout === 'hero') {
                const container = document.createElement('div');
                container.className = 'featured-container';
                renderHero(section, container);
                el.appendChild(container);
            } else {
                const grid = document.createElement('div');
                grid.className = 'grid ' + (section.layout === 'tall' ? 'grid-tall' : 'grid-wide');
                grid.id = section.id + '-grid';
                (section.items || []).forEach(p => grid.appendChild(createGridItem(p)));
                el.appendChild(grid);
            }
            root.appendChild(el);
        });
    }

    /**
     * A hero section: each group (row) is one ordered list of videos of both
     * shapes, and the row lays itself out by counting its long-forms:
     *   none      -> a full-width row of shorts under the row header (a series);
     *   one       -> the big tile with the shorts beside it (the classic row);
     *   two plus  -> the long-forms side by side on top, the shorts beneath.
     * The row header is the group's label, else the first long-form's channel,
     * else the section title; the shorts label is the group's shortsLabel, else
     * "Related shorts". Every header string comes from the config.
     */
    function renderHero(section, container) {
        (section.groups || []).forEach(group => {
            if (!group) return;
            const items = Array.isArray(group.items) ? group.items : [];
            if (!items.length) return;
            const longs = items.filter(p => p.category === 'long-form');
            const shorts = items.filter(p => p.category !== 'long-form');
            const mode = longs.length === 0 ? 'shorts-only' : longs.length === 1 ? 'lead' : 'tiers';

            const groupEl = document.createElement('div');
            groupEl.className = 'featured-group ' + mode;
            const label = group.label || (longs[0] && longs[0].channelName) || section.title || '';

            const eyebrow = document.createElement('span');
            eyebrow.className = 'featured-eyebrow';
            eyebrow.textContent = label;

            if (mode === 'lead') {
                // The header sits above the big tile and the shorts label above
                // the shorts, on one line, so the tiles line up.
                const mainEl = document.createElement('div');
                mainEl.className = 'featured-main';
                mainEl.appendChild(eyebrow);
                mainEl.appendChild(createGridItem(longs[0], { noIframePreview: true }));
                groupEl.appendChild(mainEl);
            } else {
                // No single big tile to sit above: the header spans the row.
                groupEl.appendChild(eyebrow);
                if (mode === 'tiers') {
                    const longRow = document.createElement('div');
                    longRow.className = 'featured-long-row';
                    longs.forEach(p => {
                        const cell = document.createElement('div');
                        cell.className = 'featured-main';
                        cell.appendChild(createGridItem(p, { noIframePreview: true }));
                        longRow.appendChild(cell);
                    });
                    groupEl.appendChild(longRow);
                }
            }

            if (shorts.length) {
                const shortsEl = document.createElement('div');
                shortsEl.className = 'featured-shorts';

                if (mode !== 'shorts-only') {
                    const shortsLabel = document.createElement('span');
                    shortsLabel.className = 'featured-shorts-label';
                    shortsLabel.textContent = group.shortsLabel || 'Related shorts';
                    shortsEl.appendChild(shortsLabel);
                }

                const viewport = document.createElement('div');
                viewport.className = 'featured-shorts-viewport';

                const row = document.createElement('div');
                row.className = 'featured-shorts-row';
                // noIframePreview: YouTube's iframe preview shows player chrome
                // (Powered by X overlay, prev/pause/next, YouTube logo) which
                // looks terrible on a curated showcase tile. Local clip if
                // available, else just the static thumbnail on hover.
                shorts.forEach(s => row.appendChild(createGridItem(s, { noIframePreview: true })));
                viewport.appendChild(row);

                // Nav arrows are mounted lazily once the row is measured to
                // overflow (more shorts than fit in view).
                setupShortsNav(viewport, row);

                shortsEl.appendChild(viewport);
                groupEl.appendChild(shortsEl);
            }

            container.appendChild(groupEl);
        });
    }

    /**
     * Attach prev/next nav buttons to a featured-shorts viewport when the row
     * overflows. No-op on touch devices (mobile uses native swipe via the CSS
     * overflow-x: auto path) and when the row fits without scrolling.
     */
    function setupShortsNav(viewport, row) {
        const ARROW_LEFT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>';
        const ARROW_RIGHT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>';

        const prev = document.createElement('button');
        prev.type = 'button';
        prev.className = 'featured-shorts-nav prev';
        prev.setAttribute('aria-label', 'Previous shorts');
        prev.innerHTML = ARROW_LEFT;

        const next = document.createElement('button');
        next.type = 'button';
        next.className = 'featured-shorts-nav next';
        next.setAttribute('aria-label', 'Next shorts');
        next.innerHTML = ARROW_RIGHT;

        // EDGE_THRESHOLD absorbs sub-pixel rounding from scroll-snap; tiles are
        // ~190px so 8px is well below "one tile away" but big enough to catch
        // 1-2px snap noise reliably.
        const EDGE_THRESHOLD = 8;

        const updateState = () => {
            const overflow = row.scrollWidth - row.clientWidth;
            if (overflow <= 1) {
                prev.hidden = true;
                next.hidden = true;
                return;
            }
            prev.hidden = false;
            next.hidden = false;
            prev.disabled = row.scrollLeft <= EDGE_THRESHOLD;
            next.disabled = row.scrollLeft >= overflow - EDGE_THRESHOLD;
        };

        const step = () => {
            // Scroll by one tile-width plus the gap so a click advances exactly
            // one card and snap settles on a tile boundary.
            const tile = row.querySelector('.grid-item');
            if (!tile) return row.clientWidth;
            const styles = getComputedStyle(row);
            const gap = parseFloat(styles.columnGap || styles.gap || '0') || 0;
            return tile.getBoundingClientRect().width + gap;
        };

        // scroll events from smooth-scrollBy are coalesced and may not fire on
        // the final paint, so re-check after the scroll has settled. 350ms is
        // longer than the browser's smooth-scroll duration but short enough that
        // the disabled state appears responsive after a click.
        const scheduleSettleCheck = () => {
            requestAnimationFrame(updateState);
            setTimeout(updateState, 350);
        };

        prev.addEventListener('click', () => {
            row.scrollBy({ left: -step(), behavior: 'smooth' });
            scheduleSettleCheck();
        });
        next.addEventListener('click', () => {
            row.scrollBy({ left: step(), behavior: 'smooth' });
            scheduleSettleCheck();
        });

        row.addEventListener('scroll', updateState, { passive: true });
        // scrollend fires once a scroll (programmatic or user) fully settles —
        // not yet universal but a no-op where unsupported (we still poll above).
        row.addEventListener('scrollend', updateState, { passive: true });
        window.addEventListener('resize', updateState);
        if (typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(updateState).observe(row);
        }

        viewport.appendChild(prev);
        viewport.appendChild(next);

        // Initial measurement is retried at multiple ticks because rAF alone
        // sometimes fires before the row's flex children have computed widths
        // (observed: hidden state stuck at default false even with overflow=0
        // until a resize event re-triggered updateState). The cheap retries
        // catch whatever post-layout tick the row actually settles on.
        const initSettle = () => {
            updateState();
            requestAnimationFrame(updateState);
            setTimeout(updateState, 100);
            setTimeout(updateState, 500);
        };
        initSettle();
        // Re-run once each thumbnail image decodes; flex-basis is fixed but the
        // first reliable layout often coincides with the first image load.
        row.querySelectorAll('img').forEach(img => {
            if (img.complete) return;
            img.addEventListener('load', updateState, { once: true });
            img.addEventListener('error', updateState, { once: true });
        });
    }

    // ============================================
    // Lightbox
    // ============================================

    // Element that had focus before the lightbox opened, so we can restore it on close.
    let lightboxReturnFocus = null;

    function getLightboxFocusable() {
        if (!lightbox) return [];
        return Array.from(lightbox.querySelectorAll(
            'button, a[href], video, iframe, [tabindex]:not([tabindex="-1"])'
        )).filter(el => el.offsetParent !== null || el === document.activeElement);
    }

    // Shared "lightbox is now open" finalisation: show it, lock scroll, move focus
    // to the close button, and remember where focus came from.
    function activateLightbox() {
        lightboxReturnFocus = document.activeElement;
        lightbox.classList.add('active');
        document.body.style.overflow = 'hidden';
        // Defer focus a tick: the lightbox transitions from visibility:hidden,
        // and a not-yet-visible element can't receive focus on the same frame.
        if (lightboxClose) {
            setTimeout(() => {
                if (lightbox.classList.contains('active')) lightboxClose.focus();
            }, 0);
        }
    }

    // Capitalise 'instagram' / 'tiktok' / 'youtube'; YouTube needs the
    // mid-word capital that a naive uppercase-first wouldn't produce.
    const PLATFORM_LABELS = { youtube: 'YouTube', instagram: 'Instagram', tiktok: 'TikTok' };

    function platformLabel(platform) {
        return PLATFORM_LABELS[platform] || (platform.charAt(0).toUpperCase() + platform.slice(1));
    }

    /**
     * Place the "Watch on <Platform>" pill right below the video container,
     * replacing any pill left over from a previous open.
     */
    function insertWatchPill(platform, url) {
        const existingBtn = videoContainer.parentElement.querySelector('.watch-on-platform');
        if (existingBtn) existingBtn.remove();
        videoContainer.insertAdjacentHTML('afterend', `
            <a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="watch-on-platform">
                Watch on ${platformLabel(platform)}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
            </a>
        `);
    }

    /**
     * Open the lightbox with a YouTube video
     */
    function openYouTubeLightbox(videoId, url) {
        if (!lightbox || !videoContainer) return;

        const embedUrl = getYouTubeEmbedUrl(videoId);

        videoContainer.innerHTML = `
            <iframe
                src="${embedUrl}"
                title="YouTube video player"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowfullscreen>
            </iframe>
        `;

        insertWatchPill('youtube', url);
        activateLightbox();
    }

    /**
     * Open the lightbox with a self-hosted copy of a video (project.videoSrc),
     * usually a Portuguese long-form carrying an English subtitle track
     * (project.subtitles). The YouTube iframe cannot take our own track, and a
     * subtitle layer drawn over it would vanish in fullscreen on iPhone, whereas
     * a native <track> on our own <video> survives every fullscreen mode. The
     * file lives on the GitHub "media" release, not in the repo (Pages 1 GB cap).
     * If the hosted copy fails to load, fall back to the plain YouTube embed so
     * the viewer still gets the video.
     */
    function openHostedLightbox(project) {
        if (!lightbox || !videoContainer) return;
        const videoId = project.videoId || project.youtubeId;
        const platform = project.platform || 'youtube';

        videoContainer.classList.add('hosted-video');
        videoContainer.innerHTML = `
            <video class="hosted-player" controls autoplay playsinline preload="metadata">
                <source src="${escapeAttr(project.videoSrc)}" type="video/mp4">
                ${trackHTML(project)}
                Your browser does not support the video tag.
            </video>
        `;

        const video = videoContainer.querySelector('video');
        // Browsers normally honour `default`, but Safari defers to the user's
        // caption preference; force the track on so the subtitles show at once.
        video.addEventListener('loadedmetadata', () => {
            for (const track of video.textTracks) {
                if (track.kind === 'subtitles') track.mode = 'showing';
            }
        }, { once: true });

        let fellBack = false;
        const fallbackToEmbed = () => {
            if (fellBack || platform !== 'youtube') return;
            fellBack = true;
            console.warn(`Hosted copy of ${videoId} failed to load; falling back to the YouTube embed`);
            const returnFocus = lightboxReturnFocus;
            videoContainer.classList.remove('hosted-video');
            openYouTubeLightbox(videoId, project.url);
            lightboxReturnFocus = returnFocus;
        };
        video.addEventListener('error', fallbackToEmbed);
        const source = video.querySelector('source');
        if (source) source.addEventListener('error', fallbackToEmbed);

        insertWatchPill(platform, project.url);
        activateLightbox();
    }

    /**
     * Open the lightbox with a local video file (Instagram/TikTok, or a YouTube
     * short whose full mp4 is in videos/source/). `project` is optional and only
     * read for a subtitle track.
     */
    function openVideoLightbox(videoId, platform, url, project) {
        if (!lightbox || !videoContainer) return;

        // Mark container as vertical video
        videoContainer.classList.add('vertical-video');

        const videoPath = `videos/source/${videoId}.mp4`;

        videoContainer.innerHTML = `
            <div class="vertical-video-wrapper">
                <video
                    class="lightbox-video"
                    src="${videoPath}"
                    controls
                    autoplay
                    playsinline>
                    ${trackHTML(project)}
                    Your browser does not support the video tag.
                </video>
            </div>
        `;

        insertWatchPill(platform, url);
        activateLightbox();
    }

    /**
     * Close the lightbox
     */
    function closeLightbox() {
        if (!lightbox || !videoContainer) return;

        // Pause any playing videos before closing and release the media resources
        // (both the src attribute and any <source> children, so the hosted copy
        // stops downloading too).
        const video = videoContainer.querySelector('video');
        if (video) {
            video.pause();
            video.removeAttribute('src');
            video.querySelectorAll('source').forEach(s => s.remove());
            video.load();
        }

        lightbox.classList.remove('active');
        videoContainer.innerHTML = '';
        videoContainer.classList.remove('vertical-video', 'hosted-video');
        // Remove button placed outside video container
        const btn = videoContainer.parentElement.querySelector('.watch-on-platform');
        if (btn) btn.remove();
        document.body.style.overflow = '';

        // Restore focus to whatever opened the lightbox.
        if (lightboxReturnFocus && typeof lightboxReturnFocus.focus === 'function') {
            lightboxReturnFocus.focus();
        }
        lightboxReturnFocus = null;
    }

    /**
     * Set up lightbox event listeners
     */
    function initLightbox() {
        if (!lightbox) return;

        if (lightboxClose) {
            lightboxClose.addEventListener('click', closeLightbox);
        }

        lightbox.addEventListener('click', (e) => {
            if (e.target === lightbox) {
                closeLightbox();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (!lightbox.classList.contains('active')) return;

            if (e.key === 'Escape') {
                closeLightbox();
                return;
            }

            // Trap Tab focus inside the lightbox while it's open.
            if (e.key === 'Tab') {
                const focusable = getLightboxFocusable();
                if (focusable.length === 0) {
                    e.preventDefault();
                    return;
                }
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                const active = document.activeElement;
                if (e.shiftKey && (active === first || !lightbox.contains(active))) {
                    e.preventDefault();
                    last.focus();
                } else if (!e.shiftKey && (active === last || !lightbox.contains(active))) {
                    e.preventDefault();
                    first.focus();
                }
            }
        });
    }

    // ============================================
    // Initialization
    // ============================================

    // ============================================
    // Mobile Tabs
    // ============================================

    function initMobileTabs() {
        const tabsContainer = document.getElementById('mobile-tabs');
        if (!tabsContainer) return;

        // One tab per rendered section, labelled with the section title.
        const sectionEls = Array.from(document.querySelectorAll('#sections-root > .section'));
        tabsContainer.innerHTML = '';
        sectionEls.forEach(sec => {
            const btn = document.createElement('button');
            btn.className = 'mobile-tab';
            btn.type = 'button';
            btn.dataset.tab = sec.id.replace(/^section-/, '');
            const t = sec.querySelector('.section-title');
            btn.textContent = (t && t.textContent) || btn.dataset.tab;
            tabsContainer.appendChild(btn);
        });
        const tabs = Array.from(tabsContainer.querySelectorAll('.mobile-tab'));
        if (!tabs.length) return;
        const defaultTab = tabs[0].dataset.tab;

        function switchTab(tabName) {
            tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
            sectionEls.forEach(sec => sec.classList.toggle('mobile-hidden', sec.id !== 'section-' + tabName));
        }

        tabs.forEach(tab => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));

        // Set initial state on mobile: show the first tab's section
        const mq = window.matchMedia('(max-width: 768px)');
        if (mq.matches) switchTab(defaultTab);

        // Listen for resize to show/hide sections appropriately
        mq.addEventListener('change', e => {
            if (e.matches) {
                const activeTab = tabsContainer.querySelector('.mobile-tab.active');
                switchTab(activeTab ? activeTab.dataset.tab : defaultTab);
            } else {
                sectionEls.forEach(sec => sec.classList.remove('mobile-hidden'));
            }
        });
    }

    // Keep --header-h in sync with the real header height so the mobile sticky
    // tabs pin flush below the (also sticky) header even as it wraps to 1-3 rows.
    function initStickyHeaderOffset() {
        const header = document.querySelector('.header');
        if (!header) return;
        const apply = () => {
            document.documentElement.style.setProperty('--header-h', header.offsetHeight + 'px');
        };
        apply();
        window.addEventListener('resize', apply);
        if (typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(apply).observe(header);
        }
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(apply);
        }
    }

    function initVideoListDropdown() {
        const toggle = document.getElementById('video-list-toggle');
        const dropdown = toggle?.closest('.video-list-dropdown');
        if (!toggle || !dropdown) return;

        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        const menu = dropdown.querySelector('.video-list-menu');
        menu.addEventListener('click', (e) => {
            e.stopPropagation();
        });

        document.addEventListener('click', () => {
            dropdown.classList.remove('open');
        });
    }

    function initCopyEmail() {
        const btn = document.getElementById('copy-email-btn');
        if (!btn) return;

        btn.addEventListener('click', () => {
            const email = btn.dataset.email;
            navigator.clipboard.writeText(email).then(() => {
                btn.classList.add('copied');
                const tooltip = document.createElement('span');
                tooltip.className = 'copy-email-tooltip';
                tooltip.textContent = 'Copied!';
                btn.appendChild(tooltip);
                setTimeout(() => {
                    btn.classList.remove('copied');
                    tooltip.remove();
                }, 1500);
            });
        });
    }

    function init() {
        if (typeof sections === 'undefined' || !Array.isArray(sections)) {
            console.error('Section data not found. Make sure projects.js is loaded before main.js');
            return;
        }

        renderSections();
        initLightbox();
        initVideoListDropdown();
        initCopyEmail();
        updateViewCounter();
        initMobileTabs();
        initStickyHeaderOffset();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
