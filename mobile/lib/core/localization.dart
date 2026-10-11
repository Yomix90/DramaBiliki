import 'package:flutter/material.dart';

class AppLocale {
  final String languageCode;
  AppLocale(this.languageCode);

  static final Map<String, Map<String, String>> _localizedValues = {
    'en': {
      'app_title': 'DramaBiliki',
      'tagline': 'Binge-worthy vertical short dramas',
      'tab_home': 'Home',
      'tab_for_you': 'For You',
      'tab_my_list': 'My List',
      'tab_profile': 'Profile',

      // Home
      'popular': 'Popular',
      'top_ranking': 'Top 10',
      'trending_now': 'Trending Now',
      'new_releases': 'New Releases',
      'continue_watching': 'Continue Watching',
      'watch_now': 'Watch Now',
      'episodes_count': 'Episodes',
      'ep': 'EP',
      'hot': 'HOT',
      'new_badge': 'NEW',
      'see_all': 'See all',

      // Detail
      'play_first_episode': 'Play EP 1',
      'resume_episode': 'Continue EP ',
      'synopsis': 'Synopsis',
      'all_episodes': 'Episodes',
      'add_my_list': 'My List',
      'in_my_list': 'Added',
      'added_to_list': 'Added to My List',
      'removed_from_list': 'Removed from My List',
      'read_more': 'More',
      'read_less': 'Less',

      // Player
      'episode': 'Episode',
      'speed': 'Speed',
      'subtitles': 'Subtitles',
      'next_episode': 'Next Episode',
      'select_episode': 'Select Episode',
      'retry': 'Retry',
      'playback_error': 'Video could not be loaded.',
      'load_error': 'Could not load content. Check your connection.',
      'swipe_next': 'Swipe up for next episode',
      'last_episode': "You've reached the final episode",
      'speed_2x': '2x speed',
      'watch_full': 'Watch full series',
      'playing': 'Playing',

      // Search
      'search': 'Search',
      'search_hint': 'Search dramas...',
      'no_results': 'No series found matching your search',
      'recent_searches': 'Recent searches',
      'hot_searches': 'Hot searches',
      'clear': 'Clear',

      // My List
      'my_list': 'My List',
      'history': 'History',
      'empty_my_list': 'Your list is empty. Tap ♥ on a drama to save it here.',
      'empty_history': 'No history yet. Episodes you watch will appear here.',
      'remove_confirm': 'Remove this drama from My List?',
      'remove': 'Remove',
      'cancel': 'Cancel',
      'explore': 'Explore dramas',

      // Profile
      'guest': 'Guest viewer',
      'stats_list': 'In My List',
      'stats_watched': 'Watched',
      'settings': 'Settings',
      'language': 'Language',
      'language_en': 'English',
      'language_fr': 'Français',
      'language_ar': 'العربية',
      'autoplay_next': 'Autoplay next episode',
      'autoplay_next_desc': 'Start the next episode automatically',
      'subtitles_default': 'Show subtitles',
      'data_saver': 'Data Saver Mode',
      'data_saver_desc': "Don't preload upcoming episodes",
      'server_url': 'Server Bridge URL',
      'server_url_updated': 'Server URL updated',
      'save': 'Save',
      'about': 'About DramaBiliki',
      'version': 'Version',
    },
    'fr': {
      'app_title': 'DramaBiliki',
      'tagline': 'Mini-dramas verticaux à dévorer',
      'tab_home': 'Accueil',
      'tab_for_you': 'Pour toi',
      'tab_my_list': 'Ma liste',
      'tab_profile': 'Profil',

      // Home
      'popular': 'Populaire',
      'top_ranking': 'Top 10',
      'trending_now': 'Tendances du moment',
      'new_releases': 'Nouveautés',
      'continue_watching': 'Continuer à regarder',
      'watch_now': 'Regarder',
      'episodes_count': 'Épisodes',
      'ep': 'ÉP',
      'hot': 'HOT',
      'new_badge': 'NOUVEAU',
      'see_all': 'Voir tout',

      // Detail
      'play_first_episode': 'Regarder ÉP 1',
      'resume_episode': 'Reprendre ÉP ',
      'synopsis': 'Synopsis',
      'all_episodes': 'Épisodes',
      'add_my_list': 'Ma liste',
      'in_my_list': 'Ajouté',
      'added_to_list': 'Ajouté à Ma liste',
      'removed_from_list': 'Retiré de Ma liste',
      'read_more': 'Plus',
      'read_less': 'Moins',

      // Player
      'episode': 'Épisode',
      'speed': 'Vitesse',
      'subtitles': 'Sous-titres',
      'next_episode': 'Épisode suivant',
      'select_episode': 'Choisir un épisode',
      'retry': 'Réessayer',
      'playback_error': 'Impossible de charger la vidéo.',
      'load_error': 'Chargement impossible. Vérifiez votre connexion.',
      'swipe_next': "Glissez vers le haut pour l'épisode suivant",
      'last_episode': 'Vous avez atteint le dernier épisode',
      'speed_2x': 'Vitesse x2',
      'watch_full': 'Voir la série complète',
      'playing': 'En cours',

      // Search
      'search': 'Recherche',
      'search_hint': 'Rechercher un drama...',
      'no_results': 'Aucune série trouvée pour cette recherche',
      'recent_searches': 'Recherches récentes',
      'hot_searches': 'Recherches populaires',
      'clear': 'Effacer',

      // My List
      'my_list': 'Ma liste',
      'history': 'Historique',
      'empty_my_list': 'Votre liste est vide. Touchez ♥ sur un drama pour l’ajouter.',
      'empty_history': 'Aucun historique. Les épisodes regardés apparaîtront ici.',
      'remove_confirm': 'Retirer ce drama de Ma liste ?',
      'remove': 'Retirer',
      'cancel': 'Annuler',
      'explore': 'Découvrir des dramas',

      // Profile
      'guest': 'Spectateur invité',
      'stats_list': 'Dans Ma liste',
      'stats_watched': 'Regardés',
      'settings': 'Paramètres',
      'language': 'Langue',
      'language_en': 'English',
      'language_fr': 'Français',
      'language_ar': 'العربية',
      'autoplay_next': 'Lecture auto. de l’épisode suivant',
      'autoplay_next_desc': 'Enchaîner automatiquement les épisodes',
      'subtitles_default': 'Afficher les sous-titres',
      'data_saver': 'Économie de données',
      'data_saver_desc': 'Ne pas précharger les épisodes suivants',
      'server_url': 'URL du serveur Bridge',
      'server_url_updated': 'URL du serveur mise à jour',
      'save': 'Enregistrer',
      'about': 'À propos de DramaBiliki',
      'version': 'Version',
    },
    'ar': {
      'app_title': 'دراما بيليكي',
      'tagline': 'مسلسلات قصيرة عمودية لا تُقاوم',
      'tab_home': 'الرئيسية',
      'tab_for_you': 'لك',
      'tab_my_list': 'قائمتي',
      'tab_profile': 'حسابي',

      // Home
      'popular': 'الأكثر شعبية',
      'top_ranking': 'أفضل 10',
      'trending_now': 'الأكثر تداولاً',
      'new_releases': 'أحدث المسلسلات',
      'continue_watching': 'متابعة المشاهدة',
      'watch_now': 'مشاهدة الآن',
      'episodes_count': 'حلقة',
      'ep': 'حلقة',
      'hot': 'رائج',
      'new_badge': 'جديد',
      'see_all': 'عرض الكل',

      // Detail
      'play_first_episode': 'مشاهدة الحلقة 1',
      'resume_episode': 'متابعة الحلقة ',
      'synopsis': 'القصة',
      'all_episodes': 'الحلقات',
      'add_my_list': 'قائمتي',
      'in_my_list': 'مضاف',
      'added_to_list': 'تمت الإضافة إلى قائمتي',
      'removed_from_list': 'تمت الإزالة من قائمتي',
      'read_more': 'المزيد',
      'read_less': 'أقل',

      // Player
      'episode': 'الحلقة',
      'speed': 'السرعة',
      'subtitles': 'الترجمة',
      'next_episode': 'الحلقة التالية',
      'select_episode': 'اختيار حلقة',
      'retry': 'إعادة المحاولة',
      'playback_error': 'تعذر تحميل الفيديو.',
      'load_error': 'تعذر تحميل المحتوى. تحقق من اتصالك.',
      'swipe_next': 'اسحب للأعلى للحلقة التالية',
      'last_episode': 'لقد وصلت إلى الحلقة الأخيرة',
      'speed_2x': 'سرعة ×2',
      'watch_full': 'مشاهدة المسلسل كاملاً',
      'playing': 'قيد التشغيل',

      // Search
      'search': 'البحث',
      'search_hint': 'ابحث عن مسلسل...',
      'no_results': 'لم يتم العثور على مسلسلات مطابقة',
      'recent_searches': 'عمليات البحث الأخيرة',
      'hot_searches': 'الأكثر بحثاً',
      'clear': 'مسح',

      // My List
      'my_list': 'قائمتي',
      'history': 'السجل',
      'empty_my_list': 'قائمتك فارغة. اضغط ♥ على أي مسلسل لحفظه هنا.',
      'empty_history': 'لا يوجد سجل بعد. ستظهر الحلقات التي تشاهدها هنا.',
      'remove_confirm': 'إزالة هذا المسلسل من قائمتي؟',
      'remove': 'إزالة',
      'cancel': 'إلغاء',
      'explore': 'استكشف المسلسلات',

      // Profile
      'guest': 'مشاهد زائر',
      'stats_list': 'في قائمتي',
      'stats_watched': 'تمت مشاهدتها',
      'settings': 'الإعدادات',
      'language': 'اللغة',
      'language_en': 'English',
      'language_fr': 'Français',
      'language_ar': 'العربية',
      'autoplay_next': 'التشغيل التلقائي للحلقة التالية',
      'autoplay_next_desc': 'بدء الحلقة التالية تلقائياً',
      'subtitles_default': 'إظهار الترجمة',
      'data_saver': 'وضع توفير البيانات',
      'data_saver_desc': 'عدم التحميل المسبق للحلقات التالية',
      'server_url': 'عنوان خادم Bridge',
      'server_url_updated': 'تم تحديث عنوان الخادم',
      'save': 'حفظ',
      'about': 'حول دراما بيليكي',
      'version': 'الإصدار',
    },
  };

  String t(String key) {
    final langDict = _localizedValues[languageCode] ?? _localizedValues['en']!;
    return langDict[key] ?? _localizedValues['en']![key] ?? key;
  }

  bool get isRTL => languageCode == 'ar';

  @visibleForTesting
  static Iterable<String> keysFor(String languageCode) => _localizedValues[languageCode]?.keys ?? const [];
}

class AppLocalizationsDelegate extends LocalizationsDelegate<AppLocale> {
  const AppLocalizationsDelegate();

  @override
  bool isSupported(Locale locale) => ['en', 'fr', 'ar'].contains(locale.languageCode);

  @override
  Future<AppLocale> load(Locale locale) async {
    return AppLocale(locale.languageCode);
  }

  @override
  bool shouldReload(AppLocalizationsDelegate old) => false;
}
