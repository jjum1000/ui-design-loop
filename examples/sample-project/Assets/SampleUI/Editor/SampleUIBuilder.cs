// Builds the sample uGUI project used by the ui-design-loop README demo and tests.
// (Re)applies sprite import settings and (re)creates every template and screen prefab.
// Prefabs are overwritten in place, so their GUIDs (in the committed .meta files) stay stable.
// Run: Unity.exe -batchmode -quit -projectPath <sample-project> -executeMethod SampleUIBuilder.BuildAll -logFile <log>
// Sprites come from tools/make_sprites.py (run it first if Assets/SampleUI/Sprites is empty).
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

public static class SampleUIBuilder
{
    #region Coding rule : Value
    private const string SpriteDir = "Assets/SampleUI/Sprites";
    private const string CommonDir = "Assets/SampleUI/UI/Common";
    private const string ContentsDir = "Assets/SampleUI/UI/Contents";
    private static readonly Vector2 RefRes = new Vector2(1920, 1080);

    // 9-slice borders in pixels (left, bottom, right, top); sprites not listed are Simple.
    private static readonly Dictionary<string, Vector4> Borders = new Dictionary<string, Vector4>
    {
        { "btn_primary", new Vector4(28, 32, 28, 28) },
        { "btn_secondary", new Vector4(28, 32, 28, 28) },
        { "panel_rounded", new Vector4(28, 28, 28, 28) },
        { "frame_popup", new Vector4(36, 36, 36, 36) },
        { "slot_frame", new Vector4(22, 22, 22, 22) },
        { "tab_off", new Vector4(24, 24, 24, 24) },
        { "tab_on", new Vector4(24, 24, 24, 24) },
        { "toggle_bg", new Vector4(20, 20, 20, 20) },
        { "pill", new Vector4(31, 31, 31, 31) },
        { "titlebar_bg", new Vector4(0, 8, 0, 0) },
        { "progress_fill", new Vector4(14, 14, 14, 14) },
    };

    private static readonly Color Navy = Hex(0x1B2440);
    private static readonly Color Slate = Hex(0x2C3A5E);
    private static readonly Color Orange = Hex(0xF28C38);
    private static readonly Color Teal = Hex(0x2BB3C0);
    private static readonly Color Red = Hex(0xE5484D);
    private static readonly Color Gold = Hex(0xF5C542);
    private static readonly Color Green = Hex(0x3CC27A);
    private static readonly Color White = Hex(0xF4F6FA);
    private static readonly Color Dim = new Color(0f, 0f, 0f, 0.6f);

    private static readonly string ButtonPrimary = CommonDir + "/Button_Primary.prefab";
    private static readonly string ButtonSecondary = CommonDir + "/Button_Secondary.prefab";
    private static readonly string ButtonClose = CommonDir + "/Button_Close.prefab";
    private static readonly string TabButton = CommonDir + "/TabButton.prefab";
    private static readonly string CurrencyUnit = CommonDir + "/CurrencyUnit.prefab";
    private static readonly string ItemSlotUnit = CommonDir + "/ItemSlotUnit.prefab";
    private static readonly string PopupFrame = CommonDir + "/PopupFrame.prefab";
    private static readonly string TitleBar = CommonDir + "/TitleBar.prefab";
    private static readonly string ToggleDefault = CommonDir + "/Toggle_Default.prefab";
    private static readonly string ProgressBar = CommonDir + "/ProgressBar.prefab";

    private static Font _font;
    private static Transform _buildCanvas;  // temporary parent canvas while screens are built (see BuildScreens)
    #endregion

    #region Coding rule : Function
    [MenuItem("Tools/Sample UI/Build All")]
    public static void BuildAll()
    {
        _font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        if (_font == null) throw new InvalidOperationException("LegacyRuntime.ttf built-in font not found");
        ImportSprites();
        BuildTemplates();
        BuildScreens();
        AssetDatabase.SaveAssets();
        Debug.Log("[SampleUIBuilder] BuildAll done");
    }

    // ---------- sprites ----------
    private static void ImportSprites()
    {
        var paths = AssetDatabase.FindAssets("t:Texture2D", new[] { SpriteDir })
            .Select(AssetDatabase.GUIDToAssetPath).Where(p => p.EndsWith(".png")).OrderBy(p => p, StringComparer.Ordinal).ToList();
        if (paths.Count == 0) throw new InvalidOperationException("no PNGs in " + SpriteDir + " (run tools/make_sprites.py)");
        foreach (var path in paths)
        {
            var ti = (TextureImporter)AssetImporter.GetAtPath(path);
            var name = System.IO.Path.GetFileNameWithoutExtension(path);
            ti.textureType = TextureImporterType.Sprite;
            ti.textureShape = TextureImporterShape.Texture2D;
            ti.spriteImportMode = SpriteImportMode.Single;
            ti.spritePixelsPerUnit = 100;
            ti.mipmapEnabled = false;
            ti.alphaIsTransparency = true;
            ti.wrapMode = TextureWrapMode.Clamp;
            ti.filterMode = FilterMode.Bilinear;
            ti.textureCompression = TextureImporterCompression.Uncompressed;
            ti.spriteBorder = Borders.TryGetValue(name, out var b) ? b : Vector4.zero;
            ti.SaveAndReimport();
        }
        Debug.Log("[SampleUIBuilder] sprites imported: " + paths.Count);
    }

    // ---------- templates (plain RectTransform roots, no Canvas) ----------
    private static void BuildTemplates()
    {
        EnsureFolder(CommonDir);

        var close = Node("Button_Close", null, Vector2.zero, new Vector2(80, 80));
        Img(close, "btn_close", Color.white);
        close.AddComponent<Button>();
        Img(Node("Icon", close.transform, Vector2.zero, new Vector2(44, 44)), "icon_close", White);
        Save(close, ButtonClose);

        Save(MakeButton("Button_Primary", "btn_primary", "OK"), ButtonPrimary);
        Save(MakeButton("Button_Secondary", "btn_secondary", "Cancel"), ButtonSecondary);

        var tab = Node("TabButton", null, Vector2.zero, new Vector2(240, 100));
        Img(tab, "tab_off", Color.white);
        tab.AddComponent<Button>();
        var selected = Stretch("Selected", tab.transform);
        Img(selected, "tab_on", Color.white).raycastTarget = false;
        selected.SetActive(false);
        Txt(Stretch("Label", tab.transform), "Tab", 34, White);
        Save(tab, TabButton);

        var cur = Node("CurrencyUnit", null, Vector2.zero, new Vector2(280, 72));
        Img(cur, "pill", Color.white);
        Img(Node("Icon", cur.transform, new Vector2(-104, 0), new Vector2(72, 72)), "icon_coin", Color.white);
        Txt(Node("Amount", cur.transform, new Vector2(30, 0), new Vector2(180, 60)), "1,000", 34, White, TextAnchor.MiddleLeft);
        Save(cur, CurrencyUnit);

        var slot = Node("ItemSlotUnit", null, Vector2.zero, new Vector2(160, 160));
        Img(slot, "slot_frame", Color.white);
        Img(Node("Grade", slot.transform, new Vector2(0, 62), new Vector2(120, 10)), null, Gold);
        Img(Node("Icon", slot.transform, new Vector2(0, -4), new Vector2(104, 104)), "icon_sword", Color.white);
        Txt(Node("Count", slot.transform, new Vector2(4, -56), new Vector2(136, 40)), "x1", 30, White, TextAnchor.MiddleRight);
        Save(slot, ItemSlotUnit);

        var bar = Node("TitleBar", null, Vector2.zero, new Vector2(1920, 120));
        Img(bar, "titlebar_bg", Color.white);
        var back = Node("BackButton", bar.transform, new Vector2(-890, 0), new Vector2(64, 64));
        Img(back, "icon_back", White);
        back.AddComponent<Button>();
        Txt(Node("Title", bar.transform, new Vector2(-520, 0), new Vector2(600, 100)), "Title", 52, White, TextAnchor.MiddleLeft);
        Inst(CurrencyUnit, bar.transform, "Coins", new Vector2(500, 0));
        var gems = Inst(CurrencyUnit, bar.transform, "Gems", new Vector2(800, 0));
        SetSprite(gems, "Icon", "icon_gem");
        SetText(gems, "Amount", "250");
        Save(bar, TitleBar);

        var popup = Node("PopupFrame", null, Vector2.zero, new Vector2(900, 640));
        Img(popup, "frame_popup", Color.white);
        Img(Node("Header", popup.transform, new Vector2(0, 250), new Vector2(860, 100)), "panel_rounded", Color.white);
        Txt(Node("Title", popup.transform, new Vector2(0, 250), new Vector2(700, 90)), "Popup Title", 46, White);
        Inst(ButtonClose, popup.transform, "CloseButton", new Vector2(410, 280));
        Node("Content", popup.transform, new Vector2(0, -50), new Vector2(840, 480));
        Save(popup, PopupFrame);

        var toggleGo = Node("Toggle_Default", null, Vector2.zero, new Vector2(360, 100));
        var bg = Node("Background", toggleGo.transform, new Vector2(-148, 0), new Vector2(64, 64));
        var bgImg = Img(bg, "toggle_bg", Color.white);
        var check = Img(Node("Checkmark", bg.transform, Vector2.zero, new Vector2(56, 56)), "toggle_check", Green);
        Txt(Node("Label", toggleGo.transform, new Vector2(52, 0), new Vector2(260, 80)), "Option", 34, White, TextAnchor.MiddleLeft);
        var toggle = toggleGo.AddComponent<Toggle>();
        toggle.targetGraphic = bgImg;
        toggle.graphic = check;
        toggle.isOn = true;
        Save(toggleGo, ToggleDefault);

        // Deliberately unused by any screen (the audit should report it).
        var progress = Node("ProgressBar", null, Vector2.zero, new Vector2(400, 40));
        Img(progress, "pill", Color.white);
        var fill = Img(Node("Fill", progress.transform, Vector2.zero, new Vector2(392, 32)), "progress_fill", Color.white);
        fill.type = Image.Type.Filled;
        fill.fillMethod = Image.FillMethod.Horizontal;
        fill.fillAmount = 0.6f;
        Save(progress, ProgressBar);
    }

    private static GameObject MakeButton(string name, string sprite, string label)
    {
        var go = Node(name, null, Vector2.zero, new Vector2(320, 112));
        Img(go, sprite, Color.white);
        go.AddComponent<Button>();
        Txt(Node("Label", go.transform, new Vector2(0, 4), new Vector2(300, 96)), label, 40, White);
        return go;
    }

    // ---------- screens (Canvas root sized to the reference resolution) ----------
    // Screens carry a Canvas on their root. A ROOT canvas drives its RectTransform and Unity saves driven
    // values as anchors 0 / size 0, so screens are built under a temporary parent canvas: the screen canvas is
    // then nested, not driven, and its 1920x1080 root rect is saved as authored.
    private static void BuildScreens()
    {
        var temp = new GameObject("__BuildCanvas", typeof(RectTransform), typeof(Canvas));
        _buildCanvas = temp.transform;
        try
        {
            BuildHome();
            BuildShop();
            BuildInventory();
            BuildSettings();
            BuildReward();
            BuildProfile();
        }
        finally
        {
            Object.DestroyImmediate(temp);
            _buildCanvas = null;
        }
    }

    private static void BuildHome()
    {
        var root = ScreenRoot("HomeView", Navy);
        var bar = Inst(TitleBar, root.transform, "TitleBar", new Vector2(0, 480));
        SetText(bar, "Title", "Home");
        SetActive(bar, "BackButton", false);
        SetText(bar, "Coins/Amount", "12,500");

        var card = Node("PlayerCard", root.transform, new Vector2(-640, 260), new Vector2(520, 200));
        Img(card, "panel_rounded", Color.white);
        Img(Node("Avatar", card.transform, new Vector2(-170, 0), new Vector2(150, 150)), "icon_avatar", Color.white);
        Txt(Node("PlayerName", card.transform, new Vector2(80, 30), new Vector2(320, 60)), "Rookie Captain", 38, White, TextAnchor.MiddleLeft);
        Txt(Node("Level", card.transform, new Vector2(80, -34), new Vector2(320, 50)), "Lv. 12", 32, Gold, TextAnchor.MiddleLeft);

        var quests = Node("QuestPanel", root.transform, new Vector2(-640, -40), new Vector2(520, 300));
        Img(quests, "panel_rounded", Color.white);
        Txt(Node("Header", quests.transform, new Vector2(0, 100), new Vector2(480, 60)), "Daily Quests", 38, Gold);
        Txt(Node("Quest1", quests.transform, new Vector2(0, 20), new Vector2(480, 50)), "Win 3 battles  1/3", 30, White, TextAnchor.MiddleLeft);
        Txt(Node("Quest2", quests.transform, new Vector2(0, -40), new Vector2(480, 50)), "Open 1 chest  0/1", 30, White, TextAnchor.MiddleLeft);

        var banner = Node("EventBanner", root.transform, new Vector2(240, 140), new Vector2(1000, 420));
        Img(banner, "panel_rounded", Teal);
        Img(Node("BannerStar", banner.transform, new Vector2(-330, 0), new Vector2(200, 200)), "icon_star", Color.white);
        Txt(Node("BannerTitle", banner.transform, new Vector2(110, 40), new Vector2(700, 90)), "Summer Festival", 64, White);
        Txt(Node("BannerSub", banner.transform, new Vector2(110, -50), new Vector2(700, 60)), "Event ends in 3 days", 34, Gold);

        var settings = Node("SettingsButton", root.transform, new Vector2(870, 340), new Vector2(110, 110));
        Img(settings, "icon_gear", White);
        settings.AddComponent<Button>();

        var play = Inst(ButtonPrimary, root.transform, "PlayButton", new Vector2(600, -330), new Vector2(480, 160));
        SetText(play, "Label", "Play");
        SetFontSize(play, "Label", 56);
        SetText(Inst(ButtonSecondary, root.transform, "ShopButton", new Vector2(-760, -380)), "Label", "Shop");
        SetText(Inst(ButtonSecondary, root.transform, "InventoryButton", new Vector2(-400, -380)), "Label", "Bag");
        SetText(Inst(ButtonSecondary, root.transform, "ProfileButton", new Vector2(-40, -380)), "Label", "Profile");
        Save(root, ScreenPath("Home", "HomeView"));
    }

    private static void BuildShop()
    {
        var root = ScreenRoot("ShopView", Navy);
        var bar = Inst(TitleBar, root.transform, "TitleBar", new Vector2(0, 480));
        SetText(bar, "Title", "Shop");
        SetText(bar, "Coins/Amount", "12,500");

        string[] tabs = { "Daily", "Gems", "Bundles" };
        for (int i = 0; i < tabs.Length; i++)
        {
            var tab = Inst(TabButton, root.transform, "Tab_" + tabs[i], new Vector2(-760 + i * 260, 330));
            SetText(tab, "Label", tabs[i]);
            if (i == 0) SetActive(tab, "Selected", true);
        }

        var grid = Node("Grid", root.transform, new Vector2(-400, -60), new Vector2(760, 520));
        var slots = new[]
        {
            ("icon_sword", "x1", Gold), ("icon_shield", "x1", Teal), ("icon_potion", "x5", White),
            ("icon_gem", "x100", Teal), ("icon_coin", "x5000", White), ("icon_star", "x3", Orange),
        };
        for (int i = 0; i < slots.Length; i++)
        {
            var pos = new Vector2(-250 + (i % 3) * 250, 130 - (i / 3) * 260);
            var slot = Inst(ItemSlotUnit, grid.transform, "Slot" + (i + 1), pos, new Vector2(200, 200));
            SetSprite(slot, "Icon", slots[i].Item1);
            SetText(slot, "Count", slots[i].Item2);
            SetColor(slot, "Grade", slots[i].Item3);
        }

        var detail = Node("DetailPanel", root.transform, new Vector2(520, -60), new Vector2(620, 640));
        Img(detail, "panel_rounded", Color.white);
        Txt(Node("ItemName", detail.transform, new Vector2(0, 250), new Vector2(560, 70)), "Iron Sword", 48, White);
        Txt(Node("ItemDesc", detail.transform, new Vector2(0, 160), new Vector2(560, 90)), "A sturdy blade for new captains.", 30, White);
        var price = Inst(CurrencyUnit, detail.transform, "Price", new Vector2(0, 50));
        SetText(price, "Amount", "1,200");
        SetText(Inst(ButtonPrimary, detail.transform, "BuyButton", new Vector2(0, -230)), "Label", "Buy");

        // Deliberate near-duplicate of Button_Primary: hand-built, NOT a prefab instance.
        var buyAll = Node("BuyAllButton", detail.transform, new Vector2(0, -100), new Vector2(320, 112));
        Img(buyAll, "btn_primary", Color.white);
        buyAll.AddComponent<Button>();
        Txt(Node("Label", buyAll.transform, new Vector2(0, 4), new Vector2(300, 96)), "Buy All", 40, White);
        Save(root, ScreenPath("Shop", "ShopView"));
    }

    private static void BuildInventory()
    {
        var root = ScreenRoot("InventoryView", Navy);
        var bar = Inst(TitleBar, root.transform, "TitleBar", new Vector2(0, 480));
        SetText(bar, "Title", "Inventory");

        var filter = Inst(ToggleDefault, root.transform, "EquippedOnlyToggle", new Vector2(-660, 330), new Vector2(420, 100));
        SetText(filter, "Label", "Equipped only");
        SetToggle(filter, false);
        Txt(Node("Capacity", root.transform, new Vector2(0, 330), new Vector2(400, 60)), "Slots 24 / 60", 34, Gold);
        SetText(Inst(ButtonSecondary, root.transform, "SortButton", new Vector2(700, 330)), "Label", "Sort");

        var grid = Node("Grid", root.transform, new Vector2(-300, -80), new Vector2(1100, 440));
        var slots = new[]
        {
            ("icon_sword", "x2", Gold), ("icon_shield", "x1", Gold), ("icon_potion", "x12", White),
            ("icon_star", "x7", Orange), ("icon_gem", "x30", Teal), ("icon_coin", "x999", White),
        };
        for (int i = 0; i < slots.Length; i++)
        {
            var pos = new Vector2(-450 + (i % 4) * 180, 100 - (i / 4) * 200);
            var slot = Inst(ItemSlotUnit, grid.transform, "Slot" + (i + 1), pos);
            SetSprite(slot, "Icon", slots[i].Item1);
            SetText(slot, "Count", slots[i].Item2);
            SetColor(slot, "Grade", slots[i].Item3);
        }

        var detail = Node("DetailPanel", root.transform, new Vector2(620, -80), new Vector2(520, 560));
        Img(detail, "panel_rounded", Color.white);
        Txt(Node("ItemName", detail.transform, new Vector2(0, 200), new Vector2(480, 70)), "Iron Sword", 46, White);
        Txt(Node("Stats", detail.transform, new Vector2(0, 80), new Vector2(480, 120)), "ATK +12\nDurability 40/40", 32, White);
        SetText(Inst(ButtonPrimary, detail.transform, "EquipButton", new Vector2(0, -180)), "Label", "Equip");
        Save(root, ScreenPath("Inventory", "InventoryView"));
    }

    private static void BuildSettings()
    {
        var root = ScreenRoot("SettingsPopup", Dim);
        var frame = Inst(PopupFrame, root.transform, "PopupFrame", new Vector2(0, 40));
        SetText(frame, "Title", "Settings");
        var content = frame.transform.Find("Content");
        string[] options = { "Sound", "Music", "Notifications" };
        for (int i = 0; i < options.Length; i++)
        {
            // Added inside the PopupFrame instance's Content (added-GameObject override).
            var opt = Inst(ToggleDefault, content, "Toggle_" + options[i], new Vector2(-120, 160 - i * 110));
            SetText(opt, "Label", options[i]);
            if (i == 2) SetToggle(opt, false);
        }
        Txt(Node("Version", root.transform, new Vector2(0, -470), new Vector2(400, 50)), "v0.1.0", 28, White);
        SetText(Inst(ButtonSecondary, root.transform, "CancelButton", new Vector2(-200, -215)), "Label", "Cancel");
        SetText(Inst(ButtonPrimary, root.transform, "SaveButton", new Vector2(200, -215)), "Label", "Save");
        Save(root, ScreenPath("Settings", "SettingsPopup"));
    }

    private static void BuildReward()
    {
        var root = ScreenRoot("RewardPopup", Dim);
        var frame = Inst(PopupFrame, root.transform, "PopupFrame", Vector2.zero, new Vector2(1000, 700));
        SetText(frame, "Title", "Rewards!");
        SetSprite(frame, "Header", "tab_on");
        SetPosition(frame, "Header", new Vector2(0, 280));
        SetPosition(frame, "Title", new Vector2(0, 280));
        SetPosition(frame, "CloseButton", new Vector2(460, 310));
        Img(Node("Burst", root.transform, new Vector2(0, 150), new Vector2(180, 180)), "icon_star", Color.white);
        var items = new[] { ("icon_coin", "x500"), ("icon_gem", "x50"), ("icon_potion", "x3") };
        for (int i = 0; i < items.Length; i++)
        {
            var slot = Inst(ItemSlotUnit, root.transform, "Reward" + (i + 1), new Vector2(-220 + i * 220, -50), new Vector2(180, 180));
            SetSprite(slot, "Icon", items[i].Item1);
            SetText(slot, "Count", items[i].Item2);
        }
        SetText(Inst(ButtonPrimary, root.transform, "ClaimButton", new Vector2(0, -250)), "Label", "Claim");
        Save(root, ScreenPath("Reward", "RewardPopup"));
    }

    private static void BuildProfile()
    {
        var root = ScreenRoot("ProfileView", Navy);
        var bar = Inst(TitleBar, root.transform, "TitleBar", new Vector2(0, 480));
        SetText(bar, "Title", "Profile");

        Img(Node("Avatar", root.transform, new Vector2(-600, 160), new Vector2(280, 280)), "icon_avatar", Color.white);
        Txt(Node("PlayerName", root.transform, new Vector2(-600, -30), new Vector2(560, 70)), "Rookie Captain", 52, White);
        Txt(Node("Guild", root.transform, new Vector2(-600, -95), new Vector2(560, 50)), "Guild: Night Owls", 32, Gold);
        var coins = Inst(CurrencyUnit, root.transform, "Coins", new Vector2(-600, -180));
        SetText(coins, "Amount", "12,500");
        var gems = Inst(CurrencyUnit, root.transform, "Gems", new Vector2(-600, -270));
        SetSprite(gems, "Icon", "icon_gem");
        SetText(gems, "Amount", "250");
        SetText(Inst(ButtonSecondary, root.transform, "EditButton", new Vector2(-600, -400)), "Label", "Edit");

        var statsTab = Inst(TabButton, root.transform, "Tab_Stats", new Vector2(100, 330));
        SetText(statsTab, "Label", "Stats");
        SetActive(statsTab, "Selected", true);
        SetText(Inst(TabButton, root.transform, "Tab_Badges", new Vector2(360, 330)), "Label", "Badges");

        var stats = Node("StatsPanel", root.transform, new Vector2(330, -40), new Vector2(980, 620));
        Img(stats, "panel_rounded", Color.white);
        string[] lines = { "Battles won   128", "Win rate   61%", "Best streak   9", "Items collected   342" };
        for (int i = 0; i < lines.Length; i++)
            Txt(Node("Stat" + (i + 1), stats.transform, new Vector2(0, 200 - i * 100), new Vector2(880, 70)), lines[i], 38, White, TextAnchor.MiddleLeft);
        SetText(Inst(ButtonPrimary, root.transform, "ShareButton", new Vector2(660, -430)), "Label", "Share");
        Save(root, ScreenPath("Profile", "ProfileView"));
    }

    // ---------- helpers ----------
    private static GameObject ScreenRoot(string name, Color background)
    {
        var go = new GameObject(name, typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        var rt = (RectTransform)go.transform;
        rt.SetParent(_buildCanvas, false);
        rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = Vector2.zero;
        rt.sizeDelta = RefRes;
        go.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
        var scaler = go.GetComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = RefRes;
        scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
        scaler.matchWidthOrHeight = 0.5f;
        Img(Stretch("Background", go.transform), null, background);
        return go;
    }

    private static string ScreenPath(string feature, string name)
    {
        var dir = ContentsDir + "/" + feature;
        EnsureFolder(dir);
        return dir + "/" + name + ".prefab";
    }

    private static GameObject Node(string name, Transform parent, Vector2 pos, Vector2 size)
    {
        var go = new GameObject(name, typeof(RectTransform));
        var rt = (RectTransform)go.transform;
        if (parent != null) rt.SetParent(parent, false);
        rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = pos;
        rt.sizeDelta = size;
        return go;
    }

    private static GameObject Stretch(string name, Transform parent)
    {
        var go = new GameObject(name, typeof(RectTransform));
        var rt = (RectTransform)go.transform;
        rt.SetParent(parent, false);
        rt.anchorMin = Vector2.zero;
        rt.anchorMax = Vector2.one;
        rt.pivot = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = Vector2.zero;
        rt.sizeDelta = Vector2.zero;
        return go;
    }

    private static Image Img(GameObject go, string sprite, Color color)
    {
        var img = go.AddComponent<Image>();
        img.sprite = sprite == null ? null : LoadSprite(sprite);
        img.color = color;
        img.type = sprite != null && Borders.ContainsKey(sprite) ? Image.Type.Sliced : Image.Type.Simple;
        return img;
    }

    private static Text Txt(GameObject go, string text, int size, Color color, TextAnchor align = TextAnchor.MiddleCenter)
    {
        var t = go.AddComponent<Text>();
        t.font = _font;
        t.text = text;
        t.fontSize = size;
        t.fontStyle = FontStyle.Bold;
        t.color = color;
        t.alignment = align;
        t.horizontalOverflow = HorizontalWrapMode.Wrap;
        t.verticalOverflow = VerticalWrapMode.Overflow;
        t.raycastTarget = false;
        return t;
    }

    private static Sprite LoadSprite(string name)
    {
        var path = SpriteDir + "/" + name + ".png";
        var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(path);
        if (sprite != null) return sprite;
        var found = string.Join(",", AssetDatabase.LoadAllAssetsAtPath(path).Select(a => a == null ? "null" : a.GetType().Name + ":" + a.name));
        throw new InvalidOperationException("sprite not found: " + path + " (assets at path: " + found + ")");
    }

    private static GameObject Inst(string prefabPath, Transform parent, string name, Vector2 pos, Vector2? size = null)
    {
        var src = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (src == null) throw new InvalidOperationException("prefab not found: " + prefabPath);
        var go = (GameObject)PrefabUtility.InstantiatePrefab(src, parent);
        go.name = name;
        var rt = (RectTransform)go.transform;
        rt.anchoredPosition = pos;
        if (size.HasValue) rt.sizeDelta = size.Value;
        Record(go);
        Record(rt);
        return go;
    }

    private static T Part<T>(GameObject inst, string path) where T : Component
    {
        var t = string.IsNullOrEmpty(path) ? inst.transform : inst.transform.Find(path);
        if (t == null) throw new InvalidOperationException(inst.name + ": child not found: " + path);
        var c = t.GetComponent<T>();
        if (c == null) throw new InvalidOperationException(inst.name + "/" + path + ": no " + typeof(T).Name);
        return c;
    }

    private static void SetText(GameObject inst, string path, string text)
    {
        var t = Part<Text>(inst, path);
        t.text = text;
        Record(t);
    }

    private static void SetFontSize(GameObject inst, string path, int size)
    {
        var t = Part<Text>(inst, path);
        t.fontSize = size;
        Record(t);
    }

    private static void SetSprite(GameObject inst, string path, string sprite)
    {
        var img = Part<Image>(inst, path);
        img.sprite = LoadSprite(sprite);
        Record(img);
    }

    private static void SetColor(GameObject inst, string path, Color color)
    {
        var g = Part<Graphic>(inst, path);
        g.color = color;
        Record(g);
    }

    private static void SetPosition(GameObject inst, string path, Vector2 pos)
    {
        var rt = Part<RectTransform>(inst, path);
        rt.anchoredPosition = pos;
        Record(rt);
    }

    private static void SetActive(GameObject inst, string path, bool active)
    {
        var go = Part<Transform>(inst, path).gameObject;
        go.SetActive(active);
        Record(go);
    }

    private static void SetToggle(GameObject inst, bool isOn)
    {
        var so = new SerializedObject(Part<Toggle>(inst, ""));
        so.FindProperty("m_IsOn").boolValue = isOn;
        so.ApplyModifiedPropertiesWithoutUndo();
    }

    private static void Record(Object o)
    {
        if (PrefabUtility.IsPartOfPrefabInstance(o)) PrefabUtility.RecordPrefabInstancePropertyModifications(o);
    }

    private static void Save(GameObject root, string path)
    {
        PrefabUtility.SaveAsPrefabAsset(root, path, out bool ok);
        Object.DestroyImmediate(root);
        if (!ok) throw new InvalidOperationException("SaveAsPrefabAsset failed: " + path);
        Debug.Log("[SampleUIBuilder] saved " + path);
    }

    private static void EnsureFolder(string path)
    {
        if (AssetDatabase.IsValidFolder(path)) return;
        var parent = System.IO.Path.GetDirectoryName(path).Replace('\\', '/');
        EnsureFolder(parent);
        AssetDatabase.CreateFolder(parent, System.IO.Path.GetFileName(path));
    }

    private static Color Hex(uint rgb)
    {
        return new Color32((byte)(rgb >> 16), (byte)(rgb >> 8), (byte)rgb, 255);
    }
    #endregion
}
