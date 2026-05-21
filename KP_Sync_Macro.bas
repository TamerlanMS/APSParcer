Attribute VB_Name = "Sheet_WV40_Module"
' =============================================================================
' ИНСТРУКЦИЯ ПО УСТАНОВКЕ:
'   1. Откройте WV_template.xlsm в Excel
'   2. Нажмите Alt+F11 (Редактор VBA)
'   3. В дереве слева найдите "Лист 'WV 4.0'" (или аналогичное имя)
'   4. Дважды кликните на нём → откроется модуль листа
'   5. Вставьте ВЕСЬ код ниже (раздел "КОД ДЛЯ МОДУЛЯ ЛИСТА WV 4.0")
'   6. Сохраните файл (Ctrl+S) и закройте редактор
'
' ТАКЖЕ в Module1 (или в ЭтаКнига) можно добавить кнопку:
'   Sub ОбновитьКП()
'       Sheets("WV 4.0").RebuildKP
'   End Sub
'
' Макрос автоматически срабатывает при изменении:
'   B (Артикул), E (Кол-во), G (Константа цена), M (Комментарии), N (Срок).
' Переносит в лист КП ТОЛЬКО найденные позиции (где колонка A = Бренд не пустая).
' =============================================================================

' ─── КОД ДЛЯ МОДУЛЯ ЛИСТА "WV 4.0" ─────────────────────────────────────────

Option Explicit

Private m_Updating As Boolean

' ── Авто-триггер при редактировании пользовательских ячеек ───────────────────
Private Sub Worksheet_Change(ByVal Target As Range)
    ' Следим только за вводными колонками: B(2), E(5), G(7), M(13), N(14)
    Dim watchCols As Variant
    watchCols = Array(2, 5, 7, 13, 14)

    Dim col  As Variant
    Dim fire As Boolean
    fire = False

    For Each col In watchCols
        If Not Intersect(Target, Me.Columns(CInt(col))) Is Nothing Then
            fire = True
            Exit For
        End If
    Next col

    If Not fire       Then Exit Sub
    If m_Updating     Then Exit Sub

    ' Форсируем пересчёт формул листа (A, C, D, J, K обновятся до записи в КП)
    Application.Calculate
    Call RebuildKP
End Sub

' ── Основная процедура: перестраивает лист КП ────────────────────────────────
Public Sub RebuildKP()
    If m_Updating Then Exit Sub
    m_Updating = True

    Dim wsWV    As Worksheet : Set wsWV    = ThisWorkbook.Sheets("WV 4.0")
    Dim wsKP    As Worksheet : Set wsKP    = ThisWorkbook.Sheets("КП")
    Dim wsConst As Worksheet : Set wsConst = ThisWorkbook.Sheets("Const")
    Dim wsBD    As Worksheet : Set wsBD    = ThisWorkbook.Sheets("БД")

    Application.ScreenUpdating = False
    Application.EnableEvents   = False

    Const KP_START As Long = 13    ' первая строка данных в КП
    Const KP_MAX   As Long = 500   ' последняя строка данных в КП

    ' ── 1. Очищаем данные КП (строки 13–500, колонки A–N) ────────────────────
    wsKP.Range("A" & KP_START & ":N" & KP_MAX).ClearContents

    ' ── 2. Кэшируем курс валюты для каждого бренда из Const ──────────────────
    '       Const: H(8)=Бренд, L(12)=Курс к тенге
    Dim cLast As Long
    cLast = wsConst.Cells(wsConst.Rows.Count, 8).End(xlUp).Row

    Dim arrBrand() As String
    Dim arrCur()   As Double
    Dim nBrands    As Long
    nBrands = 0

    If cLast >= 2 Then
        ReDim arrBrand(1 To cLast - 1)
        ReDim arrCur(1 To cLast - 1)
        Dim cb As Long
        For cb = 2 To cLast
            Dim bk As String
            bk = UCase(Trim(CStr(wsConst.Cells(cb, 8).Value)))
            If bk <> "" Then
                nBrands = nBrands + 1
                arrBrand(nBrands) = bk
                Dim cv As Double
                cv = Val(CStr(wsConst.Cells(cb, 12).Value))
                arrCur(nBrands) = IIf(cv > 0, cv, 1)
            End If
        Next cb
    End If

    ' ── 3. Перебираем строки WV 4.0 и заполняем КП ───────────────────────────
    Dim wvLast As Long
    wvLast = wsWV.Cells(wsWV.Rows.Count, 2).End(xlUp).Row  ' по колонке B

    Dim kpRow As Long
    kpRow = KP_START

    Dim iRow As Long
    For iRow = 2 To wvLast
        If kpRow > KP_MAX Then Exit For

        Dim sBrand   As String : sBrand   = Trim(CStr(wsWV.Cells(iRow,  1).Value)) ' A Бренд (формула)
        Dim sArticle As String : sArticle = Trim(CStr(wsWV.Cells(iRow,  2).Value)) ' B Артикул (ввод)

        ' Пустая строка или не найдено в БД → пропускаем
        If sArticle = "" Or sBrand = "" Then GoTo NextRow

        Dim dQty     As Double : dQty = Val(CStr(wsWV.Cells(iRow, 5).Value))       ' E Кол-во
        If dQty = 0 Then dQty = 1

        Dim dPriceKP As Double : dPriceKP = Val(CStr(wsWV.Cells(iRow, 10).Value))  ' J Цена КП
        Dim dSumKP   As Double : dSumKP   = Val(CStr(wsWV.Cells(iRow, 11).Value))  ' K Сумма КП
        Dim sKazCode As String : sKazCode = CStr(wsWV.Cells(iRow, 12).Value)       ' L Код КазНИИСА
        Dim sComment As String : sComment = CStr(wsWV.Cells(iRow, 13).Value)       ' M Комментарии
        Dim sDeliv   As String : sDeliv   = CStr(wsWV.Cells(iRow, 14).Value)       ' N Срок
        Dim sName    As String : sName    = CStr(wsWV.Cells(iRow,  3).Value)       ' C Наименование
        Dim sUnit    As String : sUnit    = CStr(wsWV.Cells(iRow,  4).Value)       ' D Ед.изм.

        ' Курс валюты для бренда
        Dim dCur As Double : dCur = 1
        Dim ib As Long
        For ib = 1 To nBrands
            If arrBrand(ib) = UCase(sBrand) Then
                dCur = arrCur(ib)
                Exit For
            End If
        Next ib

        ' VLOOKUP по артикулу в БД для получения КазНИИСА(E) и РРЦ(F)
        '   БД: B=Артикул, C=Наим., D=Ед.изм., E=КазНИИСА, F=РРЦ, G=МРЦ, ...
        Dim rawKaz As Double : rawKaz = 0
        Dim rawRRC As Double : rawRRC = 0
        On Error Resume Next
        rawKaz = WorksheetFunction.VLookup(sArticle, wsBD.Range("B:E"), 4, False)
        rawRRC = WorksheetFunction.VLookup(sArticle, wsBD.Range("B:F"), 5, False)
        On Error GoTo 0

        Dim dPrKaz As Double : dPrKaz = 0
        Dim dPrRRC As Double : dPrRRC = 0
        If rawKaz > 0 Then dPrKaz = Application.WorksheetFunction.RoundUp(rawKaz * dCur, 0)
        If rawRRC > 0 Then dPrRRC = Application.WorksheetFunction.RoundUp(rawRRC * dCur, 0)

        ' Запись в КП
        With wsKP
            .Cells(kpRow,  1).Value = sBrand                                       ' A Бренд
            .Cells(kpRow,  2).Value = sArticle                                     ' B Артикул
            .Cells(kpRow,  3).Value = sName                                        ' C Наименование
            .Cells(kpRow,  4).Value = sUnit                                        ' D Ед.изм.
            .Cells(kpRow,  5).Value = dQty                                         ' E Кол-во
            If dPriceKP > 0 Then .Cells(kpRow,  6).Value = dPriceKP               ' F Цена КП
            If dSumKP   > 0 Then .Cells(kpRow,  7).Value = dSumKP                 ' G Сумма КП
            If sComment <> "" Then .Cells(kpRow,  8).Value = sComment             ' H Комментарии
            If sDeliv   <> "" Then .Cells(kpRow,  9).Value = sDeliv               ' I Срок поставки
            If dPrKaz   > 0 Then .Cells(kpRow, 10).Value = dPrKaz                 ' J Цена КазНИИСА
            If dPrKaz   > 0 Then .Cells(kpRow, 11).Value = dPrKaz * dQty          ' K Сумма КазНИИСА
            If sKazCode <> "" Then .Cells(kpRow, 12).Value = sKazCode             ' L Код КазНИИСА
            If dPrRRC   > 0 Then .Cells(kpRow, 13).Value = dPrRRC                 ' M РРЦ в тнг
            If dPrRRC   > 0 Then .Cells(kpRow, 14).Value = dPrRRC * dQty          ' N Сумма РРЦ
        End With

        kpRow = kpRow + 1
NextRow:
    Next iRow

    Application.EnableEvents   = True
    Application.ScreenUpdating = True
    m_Updating = False
End Sub
