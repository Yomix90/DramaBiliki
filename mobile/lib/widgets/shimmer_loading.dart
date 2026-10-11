import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';
import '../core/app_theme.dart';

Widget _block({double? width, double? height, double radius = 8}) {
  return Container(
    width: width,
    height: height,
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(radius)),
  );
}

/// Skeleton of the home feed: banner + two poster rows.
class ShimmerLoadingList extends StatelessWidget {
  const ShimmerLoadingList({super.key});

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppTheme.surfaceLight,
      highlightColor: AppTheme.card,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: AspectRatio(aspectRatio: 16 / 10, child: _block(radius: 16)),
          ),
          for (var row = 0; row < 2; row++) ...[
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: _block(width: 140, height: 18, radius: 4),
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 170,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                physics: const NeverScrollableScrollPhysics(),
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: 4,
                itemBuilder: (context, index) => Padding(
                  padding: const EdgeInsetsDirectional.only(end: 10),
                  child: _block(width: 112, height: 150),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Skeleton of a 3-column poster grid.
class ShimmerGrid extends StatelessWidget {
  final int itemCount;

  const ShimmerGrid({super.key, this.itemCount = 9});

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppTheme.surfaceLight,
      highlightColor: AppTheme.card,
      child: GridView.builder(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        gridDelegate: posterGridDelegate,
        itemCount: itemCount,
        itemBuilder: (context, index) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AspectRatio(aspectRatio: 3 / 4, child: _block()),
            const SizedBox(height: 6),
            _block(height: 12, radius: 4),
            const SizedBox(height: 4),
            _block(width: 50, height: 10, radius: 4),
          ],
        ),
      ),
    );
  }
}

/// Shared 3-column grid geometry: 3:4 poster + two lines of text.
const posterGridDelegate = SliverGridDelegateWithFixedCrossAxisCount(
  crossAxisCount: 3,
  childAspectRatio: 0.5,
  crossAxisSpacing: 10,
  mainAxisSpacing: 14,
);
