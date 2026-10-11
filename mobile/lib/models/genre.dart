class GenreModel {
  final int id;
  final String slug;
  final String name;

  GenreModel({
    required this.id,
    required this.slug,
    required this.name,
  });

  factory GenreModel.fromJson(Map<String, dynamic> json) {
    return GenreModel(
      id: json['id'] as int? ?? 0,
      slug: json['slug'] as String? ?? '',
      name: json['name'] as String? ?? '',
    );
  }
}
