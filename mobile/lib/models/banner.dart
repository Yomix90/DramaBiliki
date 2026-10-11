class BannerModel {
  final int id;
  final String title;
  final String subtitle;
  final String imageUrl;
  final int? targetSeriesId;
  final String? targetSeriesSlug;

  BannerModel({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.imageUrl,
    this.targetSeriesId,
    this.targetSeriesSlug,
  });

  factory BannerModel.fromJson(Map<String, dynamic> json) {
    return BannerModel(
      id: json['id'] as int? ?? 0,
      title: json['title'] as String? ?? '',
      subtitle: json['subtitle'] as String? ?? '',
      imageUrl: json['image_url'] as String? ?? '',
      targetSeriesId: json['target_series_id'] as int?,
      targetSeriesSlug: json['target_series_slug'] as String?,
    );
  }
}
