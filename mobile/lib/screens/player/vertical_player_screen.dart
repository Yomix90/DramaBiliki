import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/repository.dart';
import '../../core/rewarded_ads.dart';
import '../../models/account.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/episode_sheet.dart';
import '../../widgets/state_views.dart';
import '../../widgets/video_pool.dart';
import '../../widgets/video_surface.dart';

/// ReelShort-style immersive player: one episode per page, swipe up for the next one.
class VerticalPlayerScreen extends ConsumerWidget {
  final int seriesId;
  final String seriesTitle;
  final int initialEpisodeNum;

  /// Where to start the initial episode; defaults to the saved progress.
  final int? startPositionSeconds;

  const VerticalPlayerScreen({
    super.key,
    required this.seriesId,
    required this.seriesTitle,
    this.initialEpisodeNum = 1,
    this.startPositionSeconds,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loc = AppLocale(ref.watch(localeProvider));
    final detailAsync = ref.watch(seriesDetailProvider('$seriesId'));

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: Colors.black,
        body: detailAsync.when(
          data: (detail) => _EpisodePager(
            detail: detail,
            initialEpisode: initialEpisodeNum,
            startPositionSeconds: startPositionSeconds,
          ),
          loading: () => const _PlayerShell(child: CircularProgressIndicator(color: AppTheme.primary)),
          error: (_, _) => _PlayerShell(
            child: ErrorView(
              message: loc.t('load_error'),
              retryLabel: loc.t('retry'),
              onRetry: () => ref.invalidate(seriesDetailProvider('$seriesId')),
            ),
          ),
        ),
      ),
    );
  }
}

class _PlayerShell extends StatelessWidget {
  final Widget child;

  const _PlayerShell({required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Center(child: child),
        SafeArea(
          child: IconButton(
            icon: const Icon(Icons.arrow_back_ios_new_rounded, color: Colors.white, size: 20),
            onPressed: () => Navigator.pop(context),
          ),
        ),
      ],
    );
  }
}

class _EpisodePager extends ConsumerStatefulWidget {
  final SeriesDetailModel detail;
  final int initialEpisode;
  final int? startPositionSeconds;

  const _EpisodePager({required this.detail, required this.initialEpisode, this.startPositionSeconds});

  @override
  ConsumerState<_EpisodePager> createState() => _EpisodePagerState();
}

class _EpisodePagerState extends ConsumerState<_EpisodePager> with WidgetsBindingObserver {
  late final PageController _pageController;
  late final VideoPool _pool;
  late final DramaRepository _repo;
  late int _current;

  double _speed = 1.0;
  bool _boosted = false;
  bool _userPaused = false;
  bool _inForeground = true;
  bool _descExpanded = false;
  bool _showEndHint = false;
  Offset? _heartPos;
  int _heartKey = 0;
  Timer? _syncTimer;

  /// Title, buttons and episode bar fade out after a few seconds of playback.
  bool _chromeVisible = true;
  Timer? _hideTimer;
  static const _chromeTimeout = Duration(seconds: 3);

  /// Episodes whose end was already handled (avoids re-triggering autoplay).
  final Set<int> _completed = {};

  /// Episodes finished during this session (merged with the server's watched flags).
  final Set<int> _watched = {};

  /// Rewarded-ad gate: episode waiting behind an ad, and episodes already counted.
  int? _adGateEpisode;
  bool _adLoading = false;
  final Set<int> _countedForAds = {};

  SeriesDetailModel get _detail => widget.detail;
  int get _seriesId => _detail.id;
  int get _total => _detail.availableEpisodes > 0 ? _detail.availableEpisodes : _detail.episodes.length;

  String _key(int ep) => 'ep$ep';
  VideoPlayerController? get _currentController => _pool[_key(_current)];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WakelockPlus.enable();
    _repo = ref.read(repositoryProvider);
    _pool = VideoPool(
      onChanged: () {
        if (mounted) setState(() {});
      },
    );

    ref.read(adsConfigProvider); // start fetching the ad policy
    _current = widget.initialEpisode.clamp(1, _total > 0 ? _total : 1);
    _pageController = PageController(initialPage: _current - 1);
    _startEpisode(_current, seekSeconds: widget.startPositionSeconds ?? _resumePointFor(_current));

    _syncTimer = Timer.periodic(const Duration(seconds: 10), (_) => _saveProgress());
  }

  @override
  void dispose() {
    _saveProgress();
    _syncTimer?.cancel();
    _hideTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    WakelockPlus.disable();
    _pageController.dispose();
    _pool.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _inForeground = true;
      if (!_userPaused && _adGateEpisode != _current) _currentController?.play();
    } else if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive) {
      _inForeground = false;
      _currentController?.pause();
      _saveProgress();
    }
  }

  // ---------------------------------------------------------------------------
  // Playback
  // ---------------------------------------------------------------------------

  int? _resumePointFor(int ep) {
    for (final e in _detail.episodes) {
      if (e.num == ep) return (!e.isWatched && e.watchedSeconds > 5) ? e.watchedSeconds : null;
    }
    return null;
  }

  Future<VideoPlayerController?> _ensure(int ep) {
    return _pool.ensure(_key(ep), _repo.streamUri(_seriesId, ep), captions: () => _repo.subtitles(_seriesId, ep));
  }

  Future<void> _startEpisode(int ep, {int? seekSeconds}) async {
    final c = await _ensure(ep);
    if (!mounted || c == null || ep != _current) return;

    // Only seek fresh controllers: a page swiped back to keeps its own position.
    if (seekSeconds != null && seekSeconds > 0 && c.value.position < const Duration(seconds: 1)) {
      final dur = c.value.duration.inSeconds;
      if (dur == 0 || seekSeconds < dur - 5) await c.seekTo(Duration(seconds: seekSeconds));
    } else if (c.value.isCompleted) {
      await c.seekTo(Duration.zero);
    }
    if (!mounted || ep != _current) return;

    await c.setPlaybackSpeed(_boosted ? 2.0 : _speed);
    c.removeListener(_onTick);
    c.addListener(_onTick);
    if (_passAdGate(ep) && !_userPaused && _inForeground) {
      await c.play();
      _scheduleHide();
    }

    _preload(ep + 1);
  }

  /// Counts watched episodes; returns false (and shows the gate) when an ad is due.
  bool _passAdGate(int ep) {
    if (_countedForAds.contains(ep)) return true;
    final cfg = ref.read(adsConfigProvider).value;
    if (cfg == null || !cfg.enabled) return true;
    final prefs = ref.read(preferencesProvider);
    final count = prefs.getAdsCounter();
    if (count >= cfg.everyNEpisodes) {
      if (_adGateEpisode != ep) setState(() => _adGateEpisode = ep);
      return false;
    }
    prefs.setAdsCounter(count + 1);
    _countedForAds.add(ep);
    if (_adGateEpisode != null) setState(() => _adGateEpisode = null);
    return true;
  }

  Future<void> _watchAd(AppLocale loc) async {
    if (_adLoading) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _adLoading = true);
    final cfg = ref.read(adsConfigProvider).value ?? AdsConfig.disabled;
    final outcome = await RewardedAds.show(cfg.rewardedUnitId);
    if (!mounted) return;
    setState(() => _adLoading = false);
    if (outcome == AdOutcome.dismissed) {
      messenger.showSnackBar(SnackBar(content: Text(loc.t('ad_not_finished'))));
      return;
    }
    // Rewarded, or no ad available: unlock the next episodes.
    await ref.read(preferencesProvider).setAdsCounter(0);
    final ep = _adGateEpisode;
    setState(() => _adGateEpisode = null);
    if (ep != null && ep == _current) _startEpisode(ep);
  }

  void _preload(int ep) {
    if (ep > _total || ref.read(settingsProvider).dataSaver) return;
    _ensure(ep);
  }

  void _onTick() {
    final c = _currentController;
    if (c == null) return;
    final v = c.value;
    // Re-arm the end-of-episode detection only once playback has really moved away
    // from the end (right after a replay, the player still reports "completed").
    if (v.duration > Duration.zero && v.position < v.duration - const Duration(seconds: 2)) {
      _completed.remove(_current);
    }
    if (_completed.contains(_current)) return;
    final nearEnd = v.duration > Duration.zero && v.position >= v.duration - const Duration(milliseconds: 300);
    if (v.isCompleted || (nearEnd && !v.isPlaying)) {
      _completed.add(_current);
      _onEpisodeCompleted();
    }
  }

  void _onEpisodeCompleted() {
    _watched.add(_current);
    _saveProgress(completed: true);
    if (_current < _total) {
      if (ref.read(settingsProvider).autoplayNext) {
        _pageController.nextPage(duration: const Duration(milliseconds: 450), curve: Curves.easeOutCubic);
      } else {
        setState(() {
          _userPaused = true;
          _chromeVisible = true;
        });
      }
    } else {
      setState(() {
        _showEndHint = true;
        _userPaused = true;
        _chromeVisible = true;
      });
    }
  }

  void _saveProgress({int? episode, bool completed = false}) {
    final ep = episode ?? _current;
    final c = _pool[_key(ep)];
    if (c == null) return;
    final pos = c.value.position.inSeconds;
    final total = c.value.duration.inSeconds;
    if (pos < 3 && !completed) return;

    _repo
        .saveProgress(
          seriesId: _seriesId,
          episodeNum: ep,
          positionSeconds: completed ? total : pos,
          totalSeconds: total,
          completed: completed || (total > 0 && pos >= total - 5),
        )
        .catchError((_) {});
  }

  void _onPageChanged(int index) {
    final previous = _current;
    final ep = index + 1;
    _saveProgress(episode: previous);
    _pool[_key(previous)]?.pause();

    setState(() {
      _current = ep;
      _userPaused = false;
      _descExpanded = false;
      _showEndHint = false;
      _chromeVisible = true;
    });
    _completed.remove(ep);
    _pool.retain({_key(ep - 1), _key(ep), _key(ep + 1)});
    _startEpisode(ep, seekSeconds: _resumePointFor(ep));
  }

  void _scheduleHide() {
    _hideTimer?.cancel();
    _hideTimer = Timer(_chromeTimeout, () {
      if (mounted && _adGateEpisode == null && (_currentController?.value.isPlaying ?? false)) {
        setState(() => _chromeVisible = false);
      }
    });
  }

  /// First tap brings the controls back; a tap while they are shown plays/pauses.
  void _onVideoTap() {
    if (!_chromeVisible) {
      setState(() => _chromeVisible = true);
      _scheduleHide();
      return;
    }
    _togglePlay();
    if (_userPaused) {
      _hideTimer?.cancel();
    } else {
      _scheduleHide();
    }
  }

  /// Keeps the controls on screen while the video is paused or finished.
  void _pinChrome() {
    _hideTimer?.cancel();
    if (!_chromeVisible) setState(() => _chromeVisible = true);
  }

  void _togglePlay() {
    final c = _currentController;
    if (c == null || _adGateEpisode == _current) return;
    if (c.value.isPlaying) {
      c.pause();
      setState(() => _userPaused = true);
      _pinChrome();
    } else {
      if (c.value.isCompleted) {
        c.seekTo(Duration.zero);
      }
      c.play();
      setState(() {
        _userPaused = false;
        _showEndHint = false;
      });
    }
  }

  void _setBoost(bool on) {
    setState(() => _boosted = on);
    _currentController?.setPlaybackSpeed(on ? 2.0 : _speed);
    if (on) HapticFeedback.lightImpact();
  }

  void _goToEpisode(int ep) {
    if (ep == _current) return;
    _pageController.jumpToPage(ep - 1);
  }

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  bool get _isFavorite => ref.read(favoritesProvider)[_seriesId] ?? _detail.isFavorite;

  Future<void> _setFavorite(bool value, {bool notify = true}) async {
    final loc = AppLocale(ref.read(localeProvider));
    final messenger = ScaffoldMessenger.of(context);
    final saved = await ref.read(favoritesProvider.notifier).setFavorite(_seriesId, value);
    if (!notify || saved != value) return;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(loc.t(value ? 'added_to_list' : 'removed_from_list')),
          duration: const Duration(milliseconds: 1400),
        ),
      );
  }

  void _onDoubleTap() {
    HapticFeedback.mediumImpact();
    setState(() => _heartKey++);
    if (!_isFavorite) _setFavorite(true);
  }

  void _showEpisodes(AppLocale loc) {
    final watched = {
      for (final e in _detail.episodes)
        if (e.isWatched) e.num,
      ..._watched,
    };
    showEpisodeSheet(
      context: context,
      title: '${_detail.title} · ${loc.t('all_episodes')} ($_total)',
      total: _total,
      current: _current,
      watched: watched,
      onSelect: _goToEpisode,
    );
  }

  void _showSpeedMenu(AppLocale loc) {
    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (sheetContext) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(loc.t('speed'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                const SizedBox(height: 16),
                Row(
                  children: [0.75, 1.0, 1.25, 1.5, 2.0].map((speed) {
                    final selected = speed == _speed;
                    return Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(10),
                          onTap: () {
                            setState(() => _speed = speed);
                            _currentController?.setPlaybackSpeed(speed);
                            Navigator.pop(sheetContext);
                          },
                          child: Container(
                            height: 44,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              gradient: selected ? AppTheme.primaryGradient : null,
                              color: selected ? null : AppTheme.surfaceLight,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Text('${speed}x', style: const TextStyle(fontWeight: FontWeight.w800)),
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  // ---------------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));
    if (_total == 0) {
      return _PlayerShell(
        child: EmptyView(icon: Icons.movie_filter_rounded, message: loc.t('playback_error')),
      );
    }

    return PageView.builder(
      controller: _pageController,
      scrollDirection: Axis.vertical,
      itemCount: _total,
      onPageChanged: _onPageChanged,
      itemBuilder: (context, index) => _buildPage(index + 1, loc),
    );
  }

  Widget _buildPage(int ep, AppLocale loc) {
    final settings = ref.watch(settingsProvider);
    final isFav = ref.watch(favoritesProvider)[_seriesId] ?? _detail.isFavorite;
    final controller = _pool[_key(ep)];
    final isCurrent = ep == _current;
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    final chromeOn = !isCurrent || _chromeVisible;

    return Stack(
      fit: StackFit.expand,
      children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _onVideoTap,
          onDoubleTapDown: (d) => _heartPos = d.localPosition,
          onDoubleTap: _onDoubleTap,
          onLongPressStart: (_) => _setBoost(true),
          onLongPressEnd: (_) => _setBoost(false),
          child: VideoSurface(
            controller: controller,
            posterUrl: _detail.coverUrl,
            hasError: _pool.hasError(_key(ep)),
            showCaptions: settings.subtitles,
            errorText: loc.t('playback_error'),
            retryText: loc.t('retry'),
            captionBottom: 170 + bottomInset,
            onRetry: () {
              _pool.reset(_key(ep));
              setState(() {});
              _startEpisode(ep);
            },
          ),
        ),

        // Paused indicator
        if (isCurrent && controller != null)
          IgnorePointer(
            child: ValueListenableBuilder<VideoPlayerValue>(
              valueListenable: controller,
              builder: (context, value, _) {
                final show = !value.isPlaying && !value.isBuffering;
                return AnimatedOpacity(
                  opacity: show ? 1 : 0,
                  duration: const Duration(milliseconds: 150),
                  child: Center(
                    child: Icon(
                      value.isCompleted ? Icons.replay_rounded : Icons.play_arrow_rounded,
                      color: Colors.white.withValues(alpha: 0.85),
                      size: 76,
                    ),
                  ),
                );
              },
            ),
          ),

        // Controls (fade out during playback, tap to bring them back)
        Positioned.fill(
          child: IgnorePointer(
            ignoring: !chromeOn,
            child: AnimatedOpacity(
              opacity: chromeOn ? 1 : 0,
              duration: const Duration(milliseconds: 250),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  const IgnorePointer(child: _Shades()),
                  // Top bar
                  Positioned(
                    top: 0,
                    left: 0,
                    right: 0,
                    child: SafeArea(
                      bottom: false,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                        child: Row(
                          children: [
                            IconButton(
                              icon: const Icon(Icons.arrow_back_ios_new_rounded, color: Colors.white, size: 20),
                              onPressed: () => Navigator.pop(context),
                            ),
                            Expanded(
                              child: Text(
                                "${loc.t('ep')} $ep",
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16),
                              ),
                            ),
                            IconButton(
                              tooltip: loc.t('subtitles'),
                              icon: Icon(
                                settings.subtitles ? Icons.closed_caption_rounded : Icons.closed_caption_off_outlined,
                                color: Colors.white,
                              ),
                              onPressed: () => ref.read(settingsProvider.notifier).setSubtitles(!settings.subtitles),
                            ),
                            TextButton(
                              onPressed: () => _showSpeedMenu(loc),
                              style: TextButton.styleFrom(
                                foregroundColor: Colors.white,
                                minimumSize: const Size(48, 40),
                              ),
                              child: Text(
                                _speed == 1.0 ? loc.t('speed') : '${_speed}x',
                                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  // Right action rail
                  PositionedDirectional(
                    end: 8,
                    bottom: 130 + bottomInset,
                    child: Column(
                      children: [
                        _RailButton(
                          icon: isFav ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                          color: isFav ? AppTheme.primary : Colors.white,
                          label: loc.t(isFav ? 'in_my_list' : 'add_my_list'),
                          onTap: () => _setFavorite(!isFav),
                        ),
                        _RailButton(
                          icon: Icons.video_library_rounded,
                          label: '$_current/$_total',
                          onTap: () => _showEpisodes(loc),
                        ),
                      ],
                    ),
                  ),

                  // Title, episode & synopsis
                  PositionedDirectional(
                    start: 14,
                    end: 84,
                    bottom: 84 + bottomInset,
                    child: GestureDetector(
                      onTap: () => setState(() => _descExpanded = !_descExpanded),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            _detail.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16),
                          ),
                          if (_detail.description.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            AnimatedSize(
                              duration: const Duration(milliseconds: 200),
                              alignment: Alignment.topCenter,
                              child: Text(
                                _detail.description,
                                maxLines: _descExpanded ? 8 : 2,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(color: Colors.white70, fontSize: 13, height: 1.35),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),

                  // End-of-series hint
                  if (isCurrent && _showEndHint)
                    Positioned(
                      left: 32,
                      right: 32,
                      bottom: 200 + bottomInset,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        decoration: BoxDecoration(color: Colors.black87, borderRadius: BorderRadius.circular(12)),
                        child: Text(
                          loc.t('last_episode'),
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: InkWell(
                      onTap: () => _showEpisodes(loc),
                      child: Container(
                        height: 48,
                        margin: EdgeInsets.only(bottom: bottomInset),
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        color: Colors.white.withValues(alpha: 0.08),
                        child: Row(
                          children: [
                            const Icon(Icons.layers_rounded, color: Colors.white, size: 18),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                "${loc.t('all_episodes')} · ${loc.t('ep')} $ep / $_total",
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13),
                              ),
                            ),
                            const Icon(Icons.keyboard_arrow_up_rounded, color: Colors.white70),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),

        // 2x badge while long-pressing
        if (isCurrent && _boosted)
          Positioned(
            top: MediaQuery.paddingOf(context).top + 64,
            left: 0,
            right: 0,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(20)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.fast_forward_rounded, color: Colors.white, size: 18),
                    const SizedBox(width: 6),
                    Text(
                      loc.t('speed_2x'),
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              ),
            ),
          ),

        // Thin progress bar: always visible, slides down when the controls hide
        AnimatedPositioned(
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
          left: 0,
          right: 0,
          bottom: chromeOn ? 48 + bottomInset : bottomInset,
          child: controller != null
              ? Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: VideoProgressBar(controller: controller),
                )
              : const SizedBox(height: 20),
        ),

        if (isCurrent && _heartPos != null && _heartKey > 0) HeartBurst(key: ValueKey(_heartKey), position: _heartPos!),

        if (isCurrent && _adGateEpisode == ep) Positioned.fill(child: _buildAdGate(loc)),
      ],
    );
  }

  Widget _buildAdGate(AppLocale loc) {
    // Opaque to taps so the video underneath cannot be resumed or liked.
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {},
      onDoubleTap: () {},
      child: ColoredBox(
        color: Colors.black.withValues(alpha: 0.82),
        child: SafeArea(
          child: Stack(
            children: [
              IconButton(
                icon: const Icon(Icons.arrow_back_ios_new_rounded, color: Colors.white, size: 20),
                onPressed: () => Navigator.pop(context),
              ),
              Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 36),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 72,
                        height: 72,
                        decoration: const BoxDecoration(gradient: AppTheme.primaryGradient, shape: BoxShape.circle),
                        child: const Icon(Icons.lock_open_rounded, color: Colors.white, size: 36),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        loc.t('ad_gate_title'),
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.white, fontSize: 21, fontWeight: FontWeight.w900),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        loc.t('ad_gate_desc'),
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.white70, height: 1.4),
                      ),
                      const SizedBox(height: 24),
                      GestureDetector(
                        onTap: () => _watchAd(loc),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 14),
                          decoration: BoxDecoration(
                            gradient: AppTheme.primaryGradient,
                            borderRadius: BorderRadius.circular(28),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (_adLoading)
                                const SizedBox(
                                  width: 20,
                                  height: 20,
                                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
                                )
                              else
                                const Icon(Icons.play_circle_fill_rounded, color: Colors.white),
                              const SizedBox(width: 10),
                              Text(
                                loc.t(_adLoading ? 'ad_loading' : 'watch_ad'),
                                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Shades extends StatelessWidget {
  const _Shades();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          height: 140,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Colors.black.withValues(alpha: 0.6), Colors.transparent],
            ),
          ),
        ),
        const Spacer(),
        Container(
          height: 300,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.bottomCenter,
              end: Alignment.topCenter,
              colors: [Colors.black.withValues(alpha: 0.85), Colors.transparent],
            ),
          ),
        ),
      ],
    );
  }
}

class _RailButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color color;

  const _RailButton({required this.icon, required this.label, required this.onTap, this.color = Colors.white});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: SizedBox(
        width: 64,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Column(
            children: [
              Icon(
                icon,
                color: color,
                size: 34,
                shadows: const [Shadow(color: Colors.black54, blurRadius: 8)],
              ),
              const SizedBox(height: 3),
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  shadows: [Shadow(color: Colors.black54, blurRadius: 6)],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
