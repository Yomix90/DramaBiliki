import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/localization.dart';
import 'package:mobile/models/series.dart';
import 'package:mobile/models/episode.dart';
import 'package:mobile/widgets/series_card.dart';

void main() {
  group('Localization tests', () {
    test('Translates keys properly in EN, FR, AR', () {
      final en = AppLocale('en');
      final fr = AppLocale('fr');
      final ar = AppLocale('ar');

      expect(en.t('trending_now'), 'Trending Now');
      expect(fr.t('trending_now'), 'Tendances du moment');
      expect(ar.t('trending_now'), 'الأكثر تداولاً');

      expect(en.isRTL, false);
      expect(fr.isRTL, false);
      expect(ar.isRTL, true);
    });
  });

  group('Data model tests', () {
    test('SeriesModel and EpisodeModel deserialize correctly from JSON', () {
      final seriesJson = {
        'id': 101,
        'source_id': '319823',
        'slug': 'sample-drama',
        'title': 'Alpha Love Story',
        'cover_url': 'https://example.com/cover.webp',
        'platform': 'DramaBox',
        'total_episodes': 50,
        'available_episodes': 48,
        'rating': 4.9,
        'genres': ['Romance', 'Werewolf'],
        'is_new': true,
        'is_popular': false,
      };

      final series = SeriesModel.fromJson(seriesJson);
      expect(series.id, 101);
      expect(series.sourceId, '319823');
      expect(series.title, 'Alpha Love Story');
      expect(series.availableEpisodes, 48);
      expect(series.genres.length, 2);

      final episodeJson = {
        'id': 1,
        'num': 2,
        'title': 'Episode 2',
        'duration': 140,
        'is_free': true,
        'is_watched': true,
        'watched_seconds': 140,
      };

      final ep = EpisodeModel.fromJson(episodeJson);
      expect(ep.num, 2);
      expect(ep.duration, 140);
      expect(ep.isWatched, true);
    });
  });

  group('Widget rendering tests', () {
    testWidgets('SeriesCard displays title and episode pill', (WidgetTester tester) async {
      final testSeries = SeriesModel(
        id: 1,
        sourceId: '123',
        slug: 'test-slug',
        title: 'Billionaire Return',
        coverUrl: 'https://example.com/cover.jpg',
        platform: 'ShortMax',
        totalEpisodes: 60,
        availableEpisodes: 60,
        rating: 4.8,
        genres: ['Drama'],
        isNew: true,
        isPopular: true,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SeriesCard(
              series: testSeries,
              onTap: () {},
            ),
          ),
        ),
      );

      expect(find.text('Billionaire Return'), findsOneWidget);
      expect(find.text('60 Ep.'), findsOneWidget);
      expect(find.text('ShortMax'), findsOneWidget);
    });
  });
}
