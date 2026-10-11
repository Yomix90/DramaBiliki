import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/app_theme.dart';
import '../core/localization.dart';
import '../core/navigation.dart';
import '../providers/app_providers.dart';
import 'series_card.dart';
import 'shimmer_loading.dart';
import 'state_views.dart';

/// Infinite 3-column grid of a genre (or the whole catalog when [genre] is empty).
class PagedSeriesGrid extends ConsumerStatefulWidget {
  final String genre;

  const PagedSeriesGrid({super.key, required this.genre});

  @override
  ConsumerState<PagedSeriesGrid> createState() => _PagedSeriesGridState();
}

class _PagedSeriesGridState extends ConsumerState<PagedSeriesGrid> with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final loc = AppLocale(ref.watch(localeProvider));
    final provider = pagedSeriesProvider(widget.genre);
    final pagedAsync = ref.watch(provider);

    return pagedAsync.when(
      loading: () => const ShimmerGrid(),
      error: (_, _) => ErrorView(
        message: loc.t('load_error'),
        retryLabel: loc.t('retry'),
        onRetry: () => ref.invalidate(provider),
      ),
      data: (paged) {
        if (paged.items.isEmpty) {
          return EmptyView(icon: Icons.movie_filter_rounded, message: loc.t('no_results'));
        }
        return RefreshIndicator(
          color: AppTheme.primary,
          backgroundColor: AppTheme.surface,
          onRefresh: () => ref.refresh(provider.future),
          child: NotificationListener<ScrollNotification>(
            onNotification: (n) {
              if (n.metrics.pixels >= n.metrics.maxScrollExtent - 600) {
                ref.read(provider.notifier).loadMore();
              }
              return false;
            },
            child: CustomScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              slivers: [
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                  sliver: SliverGrid.builder(
                    gridDelegate: posterGridDelegate,
                    itemCount: paged.items.length,
                    itemBuilder: (context, i) {
                      final s = paged.items[i];
                      return SeriesCard(
                        series: s,
                        episodesLabel: loc.t('ep'),
                        badgeHot: loc.t('hot'),
                        badgeNew: loc.t('new_badge'),
                        onTap: () => openSeries(context, s.slug),
                      );
                    },
                  ),
                ),
                SliverToBoxAdapter(
                  child: SizedBox(
                    height: 96,
                    child: paged.isLoadingMore
                        ? const Center(
                            child: SizedBox(
                              width: 22,
                              height: 22,
                              child: CircularProgressIndicator(strokeWidth: 2, color: AppTheme.primary),
                            ),
                          )
                        : null,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
