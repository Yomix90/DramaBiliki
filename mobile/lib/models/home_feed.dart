import 'banner.dart';
import 'series.dart';

class ContinueWatchingModel {
  final int seriesId;
  final String seriesSlug;
  final String title;
  final String coverUrl;
  final int episodeNum;
  final int positionSeconds;
  final int totalSeconds;
  final int progressPercent;

  ContinueWatchingModel({
    required this.seriesId,
    required this.seriesSlug,
    required this.title,
    required this.coverUrl,
    required this.episodeNum,
    required this.positionSeconds,
    required this.totalSeconds,
    required this.progressPercent,
  });

  factory ContinueWatchingModel.fromJson(Map<String, dynamic> json) {
    return ContinueWatchingModel(
      seriesId: json['series_id'] as int? ?? 0,
      seriesSlug: json['series_slug'] as String? ?? '',
      title: json['title'] as String? ?? '',
      coverUrl: json['cover_url'] as String? ?? '',
      episodeNum: json['episode_num'] as int? ?? 1,
      positionSeconds: json['position_seconds'] as int? ?? 0,
      totalSeconds: json['total_seconds'] as int? ?? 120,
      progressPercent: json['progress_percent'] as int? ?? 0,
    );
  }
}

class HomeSectionModel {
  final String id;
  final String title;
  final List<SeriesModel> series;

  HomeSectionModel({
    required this.id,
    required this.title,
    required this.series,
  });

  factory HomeSectionModel.fromJson(Map<String, dynamic> json) {
    final rawSeries = json['series'] as List<dynamic>? ?? [];
    return HomeSectionModel(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      series: rawSeries.map((e) => SeriesModel.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}

class HomeFeedModel {
  final List<BannerModel> banners;
  final List<ContinueWatchingModel> continueWatching;
  final List<HomeSectionModel> sections;

  HomeFeedModel({
    required this.banners,
    required this.continueWatching,
    required this.sections,
  });

  factory HomeFeedModel.fromJson(Map<String, dynamic> json) {
    final rawBanners = json['banners'] as List<dynamic>? ?? [];
    final rawContinue = json['continue_watching'] as List<dynamic>? ?? [];
    final rawSections = json['sections'] as List<dynamic>? ?? [];

    return HomeFeedModel(
      banners: rawBanners.map((e) => BannerModel.fromJson(e as Map<String, dynamic>)).toList(),
      continueWatching: rawContinue.map((e) => ContinueWatchingModel.fromJson(e as Map<String, dynamic>)).toList(),
      sections: rawSections.map((e) => HomeSectionModel.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}
