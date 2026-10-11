import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/navigation.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/episode_sheet.dart';
import '../../widgets/network_cover.dart';
import '../../widgets/state_views.dart';

class SeriesDetailScreen extends ConsumerStatefulWidget {
  final String idOrSlug;

  const SeriesDetailScreen({super.key, required this.idOrSlug});

  @override
  ConsumerState<SeriesDetailScreen> createState() => _SeriesDetailScreenState();
}

class _SeriesDetailScreenState extends ConsumerState<SeriesDetailScreen> {
  bool _isExpanded = false;

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));
    final seriesAsync = ref.watch(seriesDetailProvider(widget.idOrSlug));

    return Scaffold(
      backgroundColor: AppTheme.background,
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: seriesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator(color: AppTheme.primary)),
        error: (_, _) => ErrorView(
          message: loc.t('load_error'),
          retryLabel: loc.t('retry'),
          onRetry: () => ref.invalidate(seriesDetailProvider(widget.idOrSlug)),
        ),
        data: (series) => _buildContent(series, loc),
      ),
    );
  }

  Widget _buildContent(SeriesDetailModel series, AppLocale loc) {
    final isFav = ref.watch(favoritesProvider)[series.id] ?? series.isFavorite;
    final startEp = series.lastWatchedEpisode ?? 1;
    final total = series.availableEpisodes > 0 ? series.availableEpisodes : series.episodes.length;
    final watched = {for (final e in series.episodes) if (e.isWatched) e.num};
    final topInset = MediaQuery.paddingOf(context).top;

    void play(int ep) => openPlayer(
          context,
          ref,
          seriesId: series.id,
          title: series.title,
          episode: ep,
        );

    return Stack(
      children: [
        // Blurred cover backdrop
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          height: 360 + topInset,
          child: Stack(
            fit: StackFit.expand,
            children: [
              ImageFiltered(
                imageFilter: ImageFilter.blur(sigmaX: 28, sigmaY: 28),
                child: NetworkCover(url: series.coverUrl, variantWidth: 300),
              ),
              const DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Color(0x66000000), Color(0xCC07080A), AppTheme.background],
                    stops: [0, 0.65, 1],
                  ),
                ),
              ),
            ],
          ),
        ),
        CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.fromLTRB(16, topInset + 60, 16, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Poster + metadata
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Container(
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(10),
                            boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 18, offset: Offset(0, 8))],
                          ),
                          child: NetworkCover(
                            url: series.coverUrl,
                            width: 120,
                            height: 160,
                            variantWidth: 600,
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                series.title,
                                maxLines: 3,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 20,
                                  fontWeight: FontWeight.w900,
                                  color: Colors.white,
                                  height: 1.2,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Wrap(
                                spacing: 10,
                                runSpacing: 4,
                                crossAxisAlignment: WrapCrossAlignment.center,
                                children: [
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      const Icon(Icons.star_rounded, color: AppTheme.secondary, size: 16),
                                      const SizedBox(width: 2),
                                      Text(
                                        series.rating.toStringAsFixed(1),
                                        style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                                      ),
                                    ],
                                  ),
                                  Text(
                                    "$total ${loc.t('episodes_count')}",
                                    style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                                  ),
                                  if (series.platform.isNotEmpty)
                                    Text(
                                      series.platform,
                                      style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              if (series.genres.isNotEmpty)
                                Wrap(
                                  spacing: 6,
                                  runSpacing: 6,
                                  children: series.genres.take(4).map((g) {
                                    return Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                      decoration: BoxDecoration(
                                        color: Colors.white.withValues(alpha: 0.1),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(g, style: const TextStyle(fontSize: 11, color: Colors.white70)),
                                    );
                                  }).toList(),
                                ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),

                    // CTA row
                    Row(
                      children: [
                        Expanded(
                          child: GestureDetector(
                            onTap: total > 0 ? () => play(startEp) : null,
                            child: Container(
                              height: 48,
                              decoration: BoxDecoration(
                                gradient: AppTheme.primaryGradient,
                                borderRadius: BorderRadius.circular(24),
                              ),
                              child: Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 26),
                                  const SizedBox(width: 4),
                                  Text(
                                    startEp > 1 ? "${loc.t('resume_episode')}$startEp" : loc.t('play_first_episode'),
                                    style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: Colors.white),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        _CircleAction(
                          icon: isFav ? Icons.favorite_rounded : Icons.favorite_border_rounded,
                          color: isFav ? AppTheme.primary : Colors.white,
                          label: loc.t(isFav ? 'in_my_list' : 'add_my_list'),
                          onTap: () => ref.read(favoritesProvider.notifier).setFavorite(series.id, !isFav),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),

                    // Synopsis
                    if (series.description.isNotEmpty) ...[
                      GestureDetector(
                        onTap: () => setState(() => _isExpanded = !_isExpanded),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            AnimatedSize(
                              duration: const Duration(milliseconds: 200),
                              alignment: Alignment.topCenter,
                              child: Text(
                                series.description,
                                maxLines: _isExpanded ? null : 3,
                                overflow: _isExpanded ? TextOverflow.visible : TextOverflow.ellipsis,
                                style: const TextStyle(color: AppTheme.textSecondary, fontSize: 13.5, height: 1.45),
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              loc.t(_isExpanded ? 'read_less' : 'read_more'),
                              style: const TextStyle(color: Colors.white, fontSize: 12.5, fontWeight: FontWeight.w700),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 24),
                    ],

                    // Episodes
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            loc.t('all_episodes'),
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Colors.white),
                          ),
                        ),
                        Text(
                          "$total ${loc.t('episodes_count')}",
                          style: const TextStyle(color: AppTheme.textMuted, fontSize: 13),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    EpisodeGrid(
                      total: total,
                      current: series.lastWatchedEpisode,
                      watched: watched,
                      shrinkWrap: true,
                      onSelect: play,
                    ),
                    const SizedBox(height: 32),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _CircleAction extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String label;
  final VoidCallback onTap;

  const _CircleAction({required this.icon, required this.color, required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(height: 2),
          Text(label, style: const TextStyle(fontSize: 11, color: AppTheme.textSecondary)),
        ],
      ),
    );
  }
}
