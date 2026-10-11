import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_providers.dart';
import '../screens/detail/series_detail_screen.dart';
import '../screens/player/vertical_player_screen.dart';
import '../screens/search/search_screen.dart';

Future<void> openSeries(BuildContext context, String idOrSlug) {
  return Navigator.push(
    context,
    MaterialPageRoute(builder: (_) => SeriesDetailScreen(idOrSlug: idOrSlug)),
  );
}

/// Opens the vertical player, then refreshes progress-dependent data
/// (continue watching, history, detail) once the user comes back.
Future<void> openPlayer(
  BuildContext context,
  WidgetRef ref, {
  required int seriesId,
  required String title,
  int episode = 1,
  int? startPositionSeconds,
}) async {
  await Navigator.push(
    context,
    PageRouteBuilder(
      transitionDuration: const Duration(milliseconds: 280),
      reverseTransitionDuration: const Duration(milliseconds: 220),
      pageBuilder: (_, _, _) => VerticalPlayerScreen(
        seriesId: seriesId,
        seriesTitle: title,
        initialEpisodeNum: episode,
        startPositionSeconds: startPositionSeconds,
      ),
      transitionsBuilder: (_, animation, _, child) {
        final curved = CurvedAnimation(parent: animation, curve: Curves.easeOutCubic);
        return SlideTransition(
          position: Tween(begin: const Offset(0, 0.08), end: Offset.zero).animate(curved),
          child: FadeTransition(opacity: curved, child: child),
        );
      },
    ),
  );
  if (context.mounted) refreshWatchState(ref);
}

Future<void> openSearch(BuildContext context) {
  return Navigator.push(context, MaterialPageRoute(builder: (_) => const SearchScreen()));
}
