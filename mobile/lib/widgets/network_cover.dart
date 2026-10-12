import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import '../core/app_theme.dart';
import '../core/server_url.dart';

/// Asks the bridge for a resized WebP variant when the cover is served locally
/// (`/media/covers/...` supports `?w=300|600`). Remote URLs are left untouched.
String sizedCoverUrl(String url, {int? width}) {
  url = resolveServerUrl(url);
  if (width == null || url.isEmpty || !url.contains('/media/covers/') || url.contains('?')) return url;
  return '$url?w=${width <= 300 ? 300 : 600}';
}

class NetworkCover extends StatelessWidget {
  final String url;
  final double? width;
  final double? height;
  final BorderRadius borderRadius;

  /// Requested pixel width of the variant; also bounds the decoded image size in memory.
  final int? variantWidth;

  const NetworkCover({
    super.key,
    required this.url,
    this.width,
    this.height,
    this.borderRadius = BorderRadius.zero,
    this.variantWidth = 300,
  });

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: width,
      height: height,
      color: AppTheme.surfaceLight,
    );

    if (url.isEmpty) {
      return ClipRRect(
        borderRadius: borderRadius,
        child: Container(
          width: width,
          height: height,
          color: AppTheme.surfaceLight,
          child: const Icon(Icons.movie_outlined, color: AppTheme.textMuted),
        ),
      );
    }

    return ClipRRect(
      borderRadius: borderRadius,
      child: CachedNetworkImage(
        imageUrl: sizedCoverUrl(url, width: variantWidth),
        width: width,
        height: height,
        fit: BoxFit.cover,
        memCacheWidth: variantWidth != null ? variantWidth! * 2 : null,
        fadeInDuration: const Duration(milliseconds: 200),
        placeholder: (context, url) => placeholder,
        errorWidget: (context, url, error) => Container(
          width: width,
          height: height,
          color: AppTheme.surfaceLight,
          child: const Icon(Icons.movie_outlined, color: AppTheme.textMuted),
        ),
      ),
    );
  }
}
