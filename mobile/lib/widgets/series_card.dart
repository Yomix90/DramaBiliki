import 'package:flutter/material.dart';
import '../models/series.dart';
import '../core/app_theme.dart';
import 'network_cover.dart';

/// Portrait poster card (3:4) with episode count, rating and HOT/NEW badges.
/// Takes the full width of its parent: wrap it in a SizedBox in horizontal lists.
class SeriesCard extends StatelessWidget {
  final SeriesModel series;
  final VoidCallback onTap;
  final String episodesLabel;
  final String? badgeHot;
  final String? badgeNew;

  /// 1-based rank shown as a big number in the corner (Top 10 rows).
  final int? rank;

  const SeriesCard({
    super.key,
    required this.series,
    required this.onTap,
    this.episodesLabel = 'EP',
    this.badgeHot = 'HOT',
    this.badgeNew = 'NEW',
    this.rank,
  });

  @override
  Widget build(BuildContext context) {
    final badge = series.isPopular ? badgeHot : (series.isNew ? badgeNew : null);

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AspectRatio(
            aspectRatio: 3 / 4,
            child: Stack(
              fit: StackFit.expand,
              children: [
                NetworkCover(url: series.coverUrl, borderRadius: BorderRadius.circular(8)),
                // Bottom shade for the episode pill
                Positioned(
                  bottom: 0,
                  left: 0,
                  right: 0,
                  child: Container(
                    height: 44,
                    decoration: BoxDecoration(
                      borderRadius: const BorderRadius.vertical(bottom: Radius.circular(8)),
                      gradient: LinearGradient(
                        begin: Alignment.bottomCenter,
                        end: Alignment.topCenter,
                        colors: [Colors.black.withValues(alpha: 0.8), Colors.transparent],
                      ),
                    ),
                  ),
                ),
                Positioned(
                  bottom: 6,
                  left: 6,
                  right: 6,
                  child: Row(
                    children: [
                      const Icon(Icons.play_arrow_rounded, color: Colors.white, size: 14),
                      Flexible(
                        child: Text(
                          "${series.availableEpisodes} $episodesLabel",
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white),
                        ),
                      ),
                      const Spacer(),
                      const Icon(Icons.star_rounded, color: AppTheme.secondary, size: 12),
                      Text(
                        series.rating.toStringAsFixed(1),
                        style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white),
                      ),
                    ],
                  ),
                ),
                if (badge != null)
                  PositionedDirectional(
                    top: 0,
                    end: 0,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        gradient: series.isPopular ? AppTheme.primaryGradient : null,
                        color: series.isPopular ? null : const Color(0xFF2EBD85),
                        borderRadius: const BorderRadiusDirectional.only(
                          topEnd: Radius.circular(8),
                          bottomStart: Radius.circular(8),
                        ),
                      ),
                      child: Text(
                        badge,
                        style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w900, color: Colors.white),
                      ),
                    ),
                  ),
                if (series.platform.isNotEmpty && rank == null)
                  PositionedDirectional(
                    top: 6,
                    start: 6,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.6),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        series.platform,
                        style: const TextStyle(fontSize: 9, fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                    ),
                  ),
                if (rank != null)
                  PositionedDirectional(
                    top: -6,
                    start: 4,
                    child: Text(
                      '$rank',
                      style: TextStyle(
                        fontSize: 40,
                        fontWeight: FontWeight.w900,
                        fontStyle: FontStyle.italic,
                        height: 1.1,
                        color: rank! <= 3 ? AppTheme.rankColors[rank! - 1] : Colors.white,
                        shadows: const [Shadow(color: Colors.black87, blurRadius: 8)],
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            series.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
              color: AppTheme.textPrimary,
              height: 1.25,
            ),
          ),
          if (series.genres.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                series.genres.first,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 11, color: AppTheme.textMuted),
              ),
            ),
        ],
      ),
    );
  }
}
