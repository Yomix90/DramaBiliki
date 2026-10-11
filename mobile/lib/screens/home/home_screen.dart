import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/navigation.dart';
import '../../models/genre.dart';
import '../../models/home_feed.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/banner_carousel.dart';
import '../../widgets/network_cover.dart';
import '../../widgets/paged_series_grid.dart';
import '../../widgets/series_card.dart';
import '../../widgets/shimmer_loading.dart';
import '../../widgets/state_views.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  bool _continueBarDismissed = false;

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));
    final genres = ref.watch(genresProvider).value ?? const <GenreModel>[];

    return DefaultTabController(
      key: ValueKey(genres.length),
      length: genres.length + 1,
      child: Builder(builder: (context) {
        return Scaffold(
          backgroundColor: AppTheme.background,
          appBar: AppBar(
            titleSpacing: 16,
            title: const _Wordmark(),
            actions: [
              Padding(
                padding: const EdgeInsetsDirectional.only(end: 12),
                child: InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: () => openSearch(context),
                  child: Container(
                    width: 150,
                    height: 36,
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    decoration: BoxDecoration(
                      color: AppTheme.surfaceLight,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.search_rounded, color: AppTheme.textMuted, size: 18),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            loc.t('search'),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(color: AppTheme.textMuted, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
            bottom: TabBar(
              isScrollable: true,
              padding: const EdgeInsets.symmetric(horizontal: 4),
              indicatorSize: TabBarIndicatorSize.label,
              indicator: const UnderlineTabIndicator(
                borderSide: BorderSide(color: AppTheme.primary, width: 3),
                borderRadius: BorderRadius.all(Radius.circular(2)),
                insets: EdgeInsets.symmetric(horizontal: 8),
              ),
              tabs: [
                Tab(text: loc.t('popular')),
                for (final g in genres) Tab(text: g.name),
              ],
            ),
          ),
          body: Stack(
            children: [
              TabBarView(
                children: [
                  _PopularTab(
                    onOpenGenre: (slug) {
                      final idx = genres.indexWhere((g) => g.slug == slug);
                      if (idx >= 0) DefaultTabController.of(context).animateTo(idx + 1);
                    },
                  ),
                  for (final g in genres) PagedSeriesGrid(genre: g.slug),
                ],
              ),
              if (!_continueBarDismissed)
                PositionedDirectional(
                  start: 12,
                  end: 12,
                  bottom: 12,
                  child: _ContinueWatchingBar(onDismiss: () => setState(() => _continueBarDismissed = true)),
                ),
            ],
          ),
        );
      }),
    );
  }
}

class _Wordmark extends StatelessWidget {
  const _Wordmark();

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(5),
          decoration: BoxDecoration(
            gradient: AppTheme.primaryGradient,
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 20),
        ),
        const SizedBox(width: 8),
        ShaderMask(
          shaderCallback: (rect) => const LinearGradient(colors: [Colors.white, Color(0xFFFFC2CE)]).createShader(rect),
          child: const Text(
            'DramaBiliki',
            style: TextStyle(fontWeight: FontWeight.w900, fontSize: 21, letterSpacing: -0.6, color: Colors.white),
          ),
        ),
      ],
    );
  }
}

class _PopularTab extends ConsumerStatefulWidget {
  final ValueChanged<String> onOpenGenre;

  const _PopularTab({required this.onOpenGenre});

  @override
  ConsumerState<_PopularTab> createState() => _PopularTabState();
}

class _PopularTabState extends ConsumerState<_PopularTab> with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final loc = AppLocale(ref.watch(localeProvider));
    final feedAsync = ref.watch(homeFeedProvider);

    return feedAsync.when(
      loading: () => const SingleChildScrollView(child: ShimmerLoadingList()),
      error: (_, _) => ErrorView(
        message: loc.t('load_error'),
        retryLabel: loc.t('retry'),
        onRetry: () => ref.invalidate(homeFeedProvider),
      ),
      data: (feed) => RefreshIndicator(
        color: AppTheme.primary,
        backgroundColor: AppTheme.surface,
        onRefresh: () => ref.refresh(homeFeedProvider.future),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.only(top: 8, bottom: 110),
          children: [
            if (feed.banners.isNotEmpty) ...[
              BannerCarousel(
                banners: feed.banners,
                watchLabel: loc.t('watch_now'),
                onBannerTap: (banner) {
                  final target = banner.targetSeriesSlug ?? banner.targetSeriesId?.toString();
                  if (target != null) openSeries(context, target);
                },
              ),
              const SizedBox(height: 24),
            ],
            if (feed.continueWatching.isNotEmpty) ...[
              SectionHeader(title: loc.t('continue_watching')),
              _ContinueWatchingRow(items: feed.continueWatching, loc: loc),
              const SizedBox(height: 24),
            ],
            for (final section in feed.sections) ..._buildSection(section, loc),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildSection(HomeSectionModel section, AppLocale loc) {
    if (section.series.isEmpty) return const [];

    if (section.id == 'trending') {
      final top = section.series.take(10).toList();
      return [
        SectionHeader(title: '🏆 ${loc.t('top_ranking')}'),
        _HorizontalRow(series: top, loc: loc, ranked: true, itemWidth: 124),
        const SizedBox(height: 24),
      ];
    }

    if (section.id.startsWith('genre_')) {
      final slug = section.id.substring('genre_'.length);
      final items = section.series.take(6).toList();
      return [
        SectionHeader(
          title: section.title,
          actionLabel: loc.t('see_all'),
          onAction: () => widget.onOpenGenre(slug),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            padding: EdgeInsets.zero,
            gridDelegate: posterGridDelegate,
            itemCount: items.length,
            itemBuilder: (context, i) => _card(items[i], loc),
          ),
        ),
        const SizedBox(height: 16),
      ];
    }

    return [
      SectionHeader(title: section.title),
      _HorizontalRow(series: section.series, loc: loc),
      const SizedBox(height: 24),
    ];
  }

  Widget _card(SeriesModel s, AppLocale loc, {int? rank}) {
    return SeriesCard(
      series: s,
      rank: rank,
      episodesLabel: loc.t('ep'),
      badgeHot: loc.t('hot'),
      badgeNew: loc.t('new_badge'),
      onTap: () => openSeries(context, s.slug),
    );
  }
}

class _HorizontalRow extends StatelessWidget {
  final List<SeriesModel> series;
  final AppLocale loc;
  final bool ranked;
  final double itemWidth;

  const _HorizontalRow({required this.series, required this.loc, this.ranked = false, this.itemWidth = 112});

  @override
  Widget build(BuildContext context) {
    // 3:4 poster + up to three lines of text below it
    final height = itemWidth * 4 / 3 + 56;
    return SizedBox(
      height: height,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: series.length,
        separatorBuilder: (_, _) => const SizedBox(width: 10),
        itemBuilder: (context, i) {
          final s = series[i];
          return SizedBox(
            width: itemWidth,
            child: SeriesCard(
              series: s,
              rank: ranked ? i + 1 : null,
              episodesLabel: loc.t('ep'),
              badgeHot: loc.t('hot'),
              badgeNew: loc.t('new_badge'),
              onTap: () => openSeries(context, s.slug),
            ),
          );
        },
      ),
    );
  }
}

class _ContinueWatchingRow extends ConsumerWidget {
  final List<ContinueWatchingModel> items;
  final AppLocale loc;

  const _ContinueWatchingRow({required this.items, required this.loc});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return SizedBox(
      height: 178,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: items.length,
        separatorBuilder: (_, _) => const SizedBox(width: 10),
        itemBuilder: (context, i) {
          final item = items[i];
          return GestureDetector(
            onTap: () => openPlayer(
              context,
              ref,
              seriesId: item.seriesId,
              title: item.title,
              episode: item.episodeNum,
              startPositionSeconds: item.positionSeconds,
            ),
            child: SizedBox(
              width: 104,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Stack(
                    children: [
                      NetworkCover(
                        url: item.coverUrl,
                        width: 104,
                        height: 138,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      Positioned.fill(
                        child: Center(
                          child: Container(
                            padding: const EdgeInsets.all(4),
                            decoration: const BoxDecoration(color: Colors.black54, shape: BoxShape.circle),
                            child: const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 26),
                          ),
                        ),
                      ),
                      Positioned(
                        left: 0,
                        right: 0,
                        bottom: 0,
                        child: ClipRRect(
                          borderRadius: const BorderRadius.vertical(bottom: Radius.circular(8)),
                          child: LinearProgressIndicator(
                            value: (item.progressPercent / 100).clamp(0.0, 1.0),
                            minHeight: 3,
                            backgroundColor: Colors.white24,
                            valueColor: const AlwaysStoppedAnimation(AppTheme.primary),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    item.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5, color: Colors.white),
                  ),
                  Text(
                    "${loc.t('ep')} ${item.episodeNum}",
                    style: const TextStyle(fontSize: 11, color: AppTheme.primary, fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

/// Floating "resume" pill pinned at the bottom of Home, like ReelShort.
class _ContinueWatchingBar extends ConsumerWidget {
  final VoidCallback onDismiss;

  const _ContinueWatchingBar({required this.onDismiss});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loc = AppLocale(ref.watch(localeProvider));
    final items = ref.watch(homeFeedProvider).value?.continueWatching ?? const [];
    if (items.isEmpty) return const SizedBox.shrink();
    final item = items.first;

    void play() => openPlayer(
          context,
          ref,
          seriesId: item.seriesId,
          title: item.title,
          episode: item.episodeNum,
          startPositionSeconds: item.positionSeconds,
        );

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: play,
        child: Container(
          height: 64,
          padding: const EdgeInsetsDirectional.only(start: 8, end: 4),
          decoration: BoxDecoration(
            color: AppTheme.surfaceLight.withValues(alpha: 0.97),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppTheme.border),
            boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 16, offset: Offset(0, 6))],
          ),
          child: Row(
            children: [
              NetworkCover(url: item.coverUrl, width: 38, height: 50, borderRadius: BorderRadius.circular(6)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13.5),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      "${loc.t('continue_watching')} · ${loc.t('ep')} ${item.episodeNum}",
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppTheme.textSecondary, fontSize: 11.5),
                    ),
                  ],
                ),
              ),
              Container(
                width: 36,
                height: 36,
                decoration: const BoxDecoration(gradient: AppTheme.primaryGradient, shape: BoxShape.circle),
                child: const Icon(Icons.play_arrow_rounded, color: Colors.white),
              ),
              IconButton(
                icon: const Icon(Icons.close_rounded, color: AppTheme.textMuted, size: 18),
                onPressed: onDismiss,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
