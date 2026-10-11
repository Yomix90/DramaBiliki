import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/navigation.dart';
import '../../models/library.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/network_cover.dart';
import '../../widgets/series_card.dart';
import '../../widgets/shimmer_loading.dart';
import '../../widgets/state_views.dart';

class LibraryScreen extends ConsumerWidget {
  /// Switches the app to the Home tab (used by the empty states).
  final VoidCallback onExplore;

  const LibraryScreen({super.key, required this.onExplore});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final loc = AppLocale(ref.watch(localeProvider));
    final libAsync = ref.watch(libraryProvider);

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: AppTheme.background,
        appBar: AppBar(
          title: Text(loc.t('tab_my_list')),
          bottom: TabBar(
            isScrollable: true,
            padding: const EdgeInsets.symmetric(horizontal: 4),
            indicatorSize: TabBarIndicatorSize.label,
            indicator: const UnderlineTabIndicator(
              borderSide: BorderSide(color: AppTheme.primary, width: 3),
              insets: EdgeInsets.symmetric(horizontal: 8),
            ),
            tabs: [
              Tab(text: loc.t('my_list')),
              Tab(text: loc.t('history')),
            ],
          ),
        ),
        body: libAsync.when(
          loading: () => const ShimmerGrid(),
          error: (_, _) => ErrorView(
            message: loc.t('load_error'),
            retryLabel: loc.t('retry'),
            onRetry: () => ref.invalidate(libraryProvider),
          ),
          data: (library) => TabBarView(
            children: [
              _FavoritesTab(library: library, loc: loc, onExplore: onExplore),
              _HistoryTab(library: library, loc: loc, onExplore: onExplore),
            ],
          ),
        ),
      ),
    );
  }
}

class _FavoritesTab extends ConsumerWidget {
  final LibraryModel library;
  final AppLocale loc;
  final VoidCallback onExplore;

  const _FavoritesTab({required this.library, required this.loc, required this.onExplore});

  Future<void> _confirmRemove(BuildContext context, WidgetRef ref, SeriesModel s) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(s.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 17)),
        content: Text(loc.t('remove_confirm'), style: const TextStyle(color: AppTheme.textSecondary)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(loc.t('cancel'), style: const TextStyle(color: AppTheme.textSecondary)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(loc.t('remove'), style: const TextStyle(color: AppTheme.primary)),
          ),
        ],
      ),
    );
    if (ok == true) ref.read(favoritesProvider.notifier).setFavorite(s.id, false);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Hide items un-favorited in this session before the library refresh lands.
    final overrides = ref.watch(favoritesProvider);
    final items = library.favorites.where((s) => overrides[s.id] != false).toList();

    return RefreshIndicator(
      color: AppTheme.primary,
      backgroundColor: AppTheme.surface,
      onRefresh: () => ref.refresh(libraryProvider.future),
      child: items.isEmpty
          ? ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                SizedBox(
                  height: 420,
                  child: EmptyView(
                    icon: Icons.favorite_border_rounded,
                    message: loc.t('empty_my_list'),
                    actionLabel: loc.t('explore'),
                    onAction: onExplore,
                  ),
                ),
              ],
            )
          : GridView.builder(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16),
              gridDelegate: posterGridDelegate,
              itemCount: items.length,
              itemBuilder: (context, i) {
                final s = items[i];
                return GestureDetector(
                  onLongPress: () => _confirmRemove(context, ref, s),
                  child: SeriesCard(
                    series: s,
                    episodesLabel: loc.t('ep'),
                    badgeHot: null,
                    badgeNew: null,
                    onTap: () => openSeries(context, s.slug),
                  ),
                );
              },
            ),
    );
  }
}

class _HistoryTab extends ConsumerWidget {
  final LibraryModel library;
  final AppLocale loc;
  final VoidCallback onExplore;

  const _HistoryTab({required this.library, required this.loc, required this.onExplore});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = library.history;

    return RefreshIndicator(
      color: AppTheme.primary,
      backgroundColor: AppTheme.surface,
      onRefresh: () => ref.refresh(libraryProvider.future),
      child: items.isEmpty
          ? ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                SizedBox(
                  height: 420,
                  child: EmptyView(
                    icon: Icons.history_rounded,
                    message: loc.t('empty_history'),
                    actionLabel: loc.t('explore'),
                    onAction: onExplore,
                  ),
                ),
              ],
            )
          : ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16),
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 14),
              itemBuilder: (context, i) => _HistoryRow(item: items[i], loc: loc),
            ),
    );
  }
}

class _HistoryRow extends ConsumerWidget {
  final HistoryItem item;
  final AppLocale loc;

  const _HistoryRow({required this.item, required this.loc});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // A finished episode resumes on the next one; the player clamps to the last episode.
    final nextEp = item.completed ? item.episodeNum + 1 : item.episodeNum;
    void play() => openPlayer(
          context,
          ref,
          seriesId: item.seriesId,
          title: item.title,
          episode: nextEp,
          startPositionSeconds: item.completed ? 0 : item.positionSeconds,
        );

    return InkWell(
      borderRadius: BorderRadius.circular(10),
      onTap: play,
      child: Row(
        children: [
          NetworkCover(url: item.coverUrl, width: 72, height: 96, borderRadius: BorderRadius.circular(8)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w700, color: Colors.white, fontSize: 14.5),
                ),
                const SizedBox(height: 6),
                Text(
                  "${loc.t('ep')} ${item.episodeNum}",
                  style: const TextStyle(color: AppTheme.primary, fontSize: 12.5, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: item.completed ? 1 : item.progress,
                    minHeight: 3,
                    backgroundColor: Colors.white12,
                    valueColor: const AlwaysStoppedAnimation(AppTheme.primary),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Container(
            width: 40,
            height: 40,
            decoration: const BoxDecoration(gradient: AppTheme.primaryGradient, shape: BoxShape.circle),
            child: const Icon(Icons.play_arrow_rounded, color: Colors.white),
          ),
        ],
      ),
    );
  }
}
