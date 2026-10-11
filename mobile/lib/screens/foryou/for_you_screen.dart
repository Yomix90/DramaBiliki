import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';
import 'package:wakelock_plus/wakelock_plus.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/navigation.dart';
import '../../core/repository.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/episode_sheet.dart';
import '../../widgets/state_views.dart';
import '../../widgets/video_pool.dart';
import '../../widgets/video_surface.dart';

/// Discovery feed: full-screen previews of a different series on every swipe,
/// each one opening the full series exactly where the preview stopped.
class ForYouScreen extends ConsumerStatefulWidget {
  /// Whether the tab is visible; playback only runs while it is.
  final bool isActive;

  const ForYouScreen({super.key, required this.isActive});

  @override
  ConsumerState<ForYouScreen> createState() => _ForYouScreenState();
}

class _ForYouScreenState extends ConsumerState<ForYouScreen> with WidgetsBindingObserver {
  final PageController _pageController = PageController();
  late final VideoPool _pool;
  late final DramaRepository _repo;

  List<SeriesModel> _items = const [];
  int _index = 0;
  bool _activatedOnce = false;
  bool _started = false;
  bool _userPaused = false;
  bool _away = false;
  bool _inForeground = true;
  Offset? _heartPos;
  int _heartKey = 0;

  bool get _canPlay => widget.isActive && !_away && !_userPaused && _inForeground;

  String _key(int i) => i >= 0 && i < _items.length ? 's${_items[i].id}' : '';
  VideoPlayerController? get _currentController => _items.isEmpty ? null : _pool[_key(_index)];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _repo = ref.read(repositoryProvider);
    _pool = VideoPool(onChanged: () {
      if (mounted) setState(() {});
    });
    _activatedOnce = widget.isActive;
    if (widget.isActive) WakelockPlus.enable();
  }

  @override
  void didUpdateWidget(covariant ForYouScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.isActive == widget.isActive) return;
    if (widget.isActive) {
      _activatedOnce = true;
      WakelockPlus.enable();
      _resume();
    } else {
      WakelockPlus.disable();
      _pool.pauseAll();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (widget.isActive) WakelockPlus.disable();
    _pageController.dispose();
    _pool.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _inForeground = state == AppLifecycleState.resumed;
    if (_inForeground) {
      _resume();
    } else {
      _pool.pauseAll();
    }
  }

  // ---------------------------------------------------------------------------
  // Playback
  // ---------------------------------------------------------------------------

  Future<VideoPlayerController?> _ensure(int i) {
    final series = _items[i];
    return _pool.ensure(
      _key(i),
      _repo.streamUri(series.id, 1),
      captions: () => _repo.subtitles(series.id, 1),
    );
  }

  Future<void> _start(int i) async {
    final c = await _ensure(i);
    if (!mounted || c == null || i != _index) return;
    await c.setLooping(true);
    if (_canPlay) await c.play();
    if (i + 1 < _items.length && !ref.read(settingsProvider).dataSaver) _ensure(i + 1);
  }

  void _resume() {
    if (!_canPlay || _items.isEmpty) return;
    final c = _currentController;
    if (c != null) {
      c.play();
    } else {
      _start(_index);
    }
  }

  void _onPageChanged(int i) {
    _pool.pauseAll();
    setState(() {
      _index = i;
      _userPaused = false;
    });
    _pool.retain({_key(i - 1), _key(i), _key(i + 1)});
    _start(i);
    if (i >= _items.length - 3) ref.read(pagedSeriesProvider('').notifier).loadMore();
  }

  void _togglePlay() {
    final c = _currentController;
    if (c == null) return;
    if (c.value.isPlaying) {
      c.pause();
      setState(() => _userPaused = true);
    } else {
      setState(() => _userPaused = false);
      c.play();
    }
  }

  /// Leaves the feed for another screen, pausing the preview meanwhile.
  Future<void> _leaveFor(Future<void> Function() navigate) async {
    _away = true;
    _pool.pauseAll();
    await navigate();
    if (!mounted) return;
    _away = false;
    _resume();
  }

  void _watchFull(SeriesModel s, {int episode = 1}) {
    final c = _currentController;
    final position = (episode == 1 && c != null) ? c.value.position.inSeconds : null;
    _leaveFor(() => openPlayer(
          context,
          ref,
          seriesId: s.id,
          title: s.title,
          episode: episode,
          startPositionSeconds: position,
        ));
  }

  // ---------------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));

    // Nothing is fetched until the tab is opened for the first time.
    if (!_activatedOnce) return const ColoredBox(color: Colors.black);

    final feedAsync = ref.watch(pagedSeriesProvider(''));

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: ColoredBox(
        color: Colors.black,
        child: feedAsync.when(
          loading: () => const Center(child: CircularProgressIndicator(color: AppTheme.primary)),
          error: (_, _) => ErrorView(
            message: loc.t('load_error'),
            retryLabel: loc.t('retry'),
            onRetry: () => ref.invalidate(pagedSeriesProvider('')),
          ),
          data: (paged) {
            _items = paged.items;
            if (_items.isEmpty) {
              return EmptyView(icon: Icons.movie_filter_rounded, message: loc.t('no_results'));
            }
            if (!_started) {
              _started = true;
              WidgetsBinding.instance.addPostFrameCallback((_) => _start(_index));
            }
            return Stack(
              children: [
                PageView.builder(
                  controller: _pageController,
                  scrollDirection: Axis.vertical,
                  itemCount: _items.length,
                  onPageChanged: _onPageChanged,
                  itemBuilder: (context, i) => _buildPage(i, loc),
                ),
                // Header
                Positioned(
                  top: 0,
                  left: 0,
                  right: 0,
                  child: SafeArea(
                    bottom: false,
                    child: SizedBox(
                      height: 48,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Text(
                            loc.t('tab_for_you'),
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 17,
                              fontWeight: FontWeight.w800,
                              shadows: [Shadow(color: Colors.black54, blurRadius: 8)],
                            ),
                          ),
                          PositionedDirectional(
                            end: 4,
                            child: IconButton(
                              icon: const Icon(Icons.search_rounded, color: Colors.white, size: 26),
                              onPressed: () => _leaveFor(() => openSearch(context)),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildPage(int i, AppLocale loc) {
    final s = _items[i];
    final key = _key(i);
    final controller = _pool[key];
    final isCurrent = i == _index;
    final settings = ref.watch(settingsProvider);
    final libraryIds = ref.watch(libraryProvider).value?.favorites.map((f) => f.id).toSet() ?? const <int>{};
    final isFav = ref.watch(favoritesProvider)[s.id] ?? libraryIds.contains(s.id);

    return Stack(
      fit: StackFit.expand,
      children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _togglePlay,
          onDoubleTapDown: (d) => _heartPos = d.localPosition,
          onDoubleTap: () {
            HapticFeedback.mediumImpact();
            setState(() => _heartKey++);
            if (!isFav) ref.read(favoritesProvider.notifier).setFavorite(s.id, true);
          },
          child: VideoSurface(
            controller: controller,
            posterUrl: s.coverUrl,
            hasError: _pool.hasError(key),
            showCaptions: settings.subtitles,
            errorText: loc.t('playback_error'),
            retryText: loc.t('retry'),
            captionBottom: 210,
            onRetry: () {
              _pool.reset(key);
              setState(() {});
              _start(i);
            },
          ),
        ),
        IgnorePointer(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.bottomCenter,
                end: Alignment.topCenter,
                colors: [Colors.black.withValues(alpha: 0.85), Colors.transparent, Colors.transparent, Colors.black45],
                stops: const [0, 0.4, 0.8, 1],
              ),
            ),
          ),
        ),

        if (isCurrent && controller != null)
          IgnorePointer(
            child: ValueListenableBuilder<VideoPlayerValue>(
              valueListenable: controller,
              builder: (context, value, _) => AnimatedOpacity(
                opacity: !value.isPlaying && !value.isBuffering ? 1 : 0,
                duration: const Duration(milliseconds: 150),
                child: Center(
                  child: Icon(Icons.play_arrow_rounded, color: Colors.white.withValues(alpha: 0.85), size: 76),
                ),
              ),
            ),
          ),

        // Right rail
        PositionedDirectional(
          end: 8,
          bottom: 150,
          child: Column(
            children: [
              _FeedRailButton(
                icon: isFav ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                color: isFav ? AppTheme.primary : Colors.white,
                label: loc.t(isFav ? 'in_my_list' : 'add_my_list'),
                onTap: () => ref.read(favoritesProvider.notifier).setFavorite(s.id, !isFav),
              ),
              _FeedRailButton(
                icon: Icons.video_library_rounded,
                label: '${s.availableEpisodes} ${loc.t('ep')}',
                onTap: () => showEpisodeSheet(
                  context: context,
                  title: '${s.title} · ${loc.t('all_episodes')} (${s.availableEpisodes})',
                  total: s.availableEpisodes,
                  current: 1,
                  onSelect: (ep) => _watchFull(s, episode: ep),
                ),
              ),
              _FeedRailButton(
                icon: Icons.info_outline_rounded,
                label: loc.t('synopsis'),
                onTap: () => _leaveFor(() => openSeries(context, s.slug)),
              ),
            ],
          ),
        ),

        // Info + CTA
        PositionedDirectional(
          start: 14,
          end: 84,
          bottom: 26,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              GestureDetector(
                onTap: () => _leaveFor(() => openSeries(context, s.slug)),
                child: Text(
                  s.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  _Tag("${loc.t('ep')} 1 / ${s.availableEpisodes}", highlight: true),
                  for (final g in s.genres.take(3)) _Tag(g),
                ],
              ),
              const SizedBox(height: 12),
              GestureDetector(
                onTap: () => _watchFull(s),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  decoration: BoxDecoration(
                    gradient: AppTheme.primaryGradient,
                    borderRadius: BorderRadius.circular(24),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 20),
                      const SizedBox(width: 4),
                      Text(
                        loc.t('watch_full'),
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13.5),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),

        if (controller != null)
          Positioned(
            left: 12,
            right: 12,
            bottom: 0,
            child: VideoProgressBar(controller: controller),
          ),

        if (isCurrent && _heartPos != null && _heartKey > 0)
          HeartBurst(key: ValueKey(_heartKey), position: _heartPos!),
      ],
    );
  }
}

class _Tag extends StatelessWidget {
  final String text;
  final bool highlight;

  const _Tag(this.text, {this.highlight = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: highlight ? AppTheme.primary.withValues(alpha: 0.9) : Colors.white.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(text, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
    );
  }
}

class _FeedRailButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color color;

  const _FeedRailButton({required this.icon, required this.label, required this.onTap, this.color = Colors.white});

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
              Icon(icon, color: color, size: 32, shadows: const [Shadow(color: Colors.black54, blurRadius: 8)]),
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
