VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Лист2"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Option Explicit

' =============================================================================
' Лист2 = «WV 4.0»
'
' Worksheet_Change:
'   Срабатывает при изменении ячейки в столбце B (Артикул).
'   1. Ищет введённую строку в БД!B:J (точное совпадение, затем частичное).
'   2. При точном совпадении — сразу обновляет всю строку WV 4.0.
'   3. При нескольких частичных совпадениях — показывает UserForm1 для выбора.
'   4. После выбора — обновляет строку через UpdateWVRow.
'
' UpdateWVRow:
'   Обновляет ячейки строки WV 4.0 после выбора артикула:
'     A = Бренд          (БД!J)
'     B = Артикул        (уже задан)
'     C = Наименование   (БД!C)
'     D = Ед.изм.        (БД!D)
'     E = Количество     — НЕ ТРОГАЕТСЯ
'     G = Константа цены — ОЧИЩАЕТСЯ (пересчёт по формуле)
'
' Включение/выключение: Ctrl+Q (или Ctrl+Й для кириллической раскладки).
' =============================================================================

Private Sub Worksheet_Change(ByVal Target As Range)
    ' Проверяем, включён ли макрос
    If Not EnableMyMacro Then Exit Sub

    ' Проверяем, затронуты ли изменения в колонке B (Артикул)
    Dim intersectRange As Range
    Set intersectRange = Intersect(Target, Me.Columns(2))
    If intersectRange Is Nothing Then Exit Sub

    On Error GoTo CleanUp
    Application.EnableEvents = False
    Application.ScreenUpdating = False

    ' Ссылка на лист БД
    Dim wsData As Worksheet
    Set wsData = ThisWorkbook.Sheets("БД")

    ' Последняя заполненная строка в БД (по столбцу B)
    Dim lastRow As Long
    lastRow = wsData.Cells(wsData.Rows.Count, "B").End(xlUp).Row
    If lastRow < 2 Then GoTo CleanUp

    ' Читаем БД B:J в массив одной операцией
    ' Индексы: B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9
    Dim arrData As Variant
    arrData = wsData.Range("B1:J" & lastRow).Value

    Dim tCell As Range
    For Each tCell In intersectRange
        If Not IsEmpty(tCell.Value) Then
            Dim strSearch As String
            strSearch = LCase$(Trim$(CStr(tCell.Value)))

            If Len(strSearch) = 0 Then GoTo NextCell

            Dim matches As Collection
            Dim matchIndices As Collection
            Set matches = New Collection
            Set matchIndices = New Collection

            Dim exactMatchIdx As Long
            exactMatchIdx = 0

            Dim i As Long
            For i = 1 To UBound(arrData, 1)
                Dim ValB As String
                Dim valC As String
                ValB = CStr(arrData(i, 1))   ' Артикул  (col B)
                valC = CStr(arrData(i, 2))   ' Наименование (col C)

                ' 1. Точное совпадение по артикулу или наименованию
                If LCase$(ValB) = strSearch Or LCase$(valC) = strSearch Then
                    exactMatchIdx = i
                    Exit For
                End If

                ' 2. Частичное совпадение
                If InStr(1, ValB, strSearch, vbTextCompare) > 0 Or _
                   InStr(1, valC, strSearch, vbTextCompare) > 0 Then
                    matches.Add arrData(i, 1) & " - " & valC
                    matchIndices.Add i
                End If
            Next i

            If exactMatchIdx > 0 Then
                ' Точное совпадение — обновляем строку сразу
                Call UpdateWVRow(tCell, _
                    CStr(arrData(exactMatchIdx, 1)), _
                    CStr(arrData(exactMatchIdx, 2)), _
                    CStr(arrData(exactMatchIdx, 3)), _
                    CStr(arrData(exactMatchIdx, 9)))

            ElseIf matches.Count > 0 Then
                ' Частичные совпадения — показываем форму выбора
                Dim frm As UserForm1
                Set frm = New UserForm1
                frm.lstMatches.Clear

                Dim matchItem As Variant
                For Each matchItem In matches
                    frm.lstMatches.AddItem matchItem
                Next matchItem

                Dim result As String
                result = frm.GetSelectedValue
                Unload frm

                If result <> "" Then
                    ' Найти индекс выбранного элемента
                    Dim selectedIdx As Long
                    selectedIdx = 0
                    Dim j As Long
                    For j = 1 To matches.Count
                        If matches(j) = result Then
                            selectedIdx = matchIndices(j)
                            Exit For
                        End If
                    Next j

                    If selectedIdx > 0 Then
                        Call UpdateWVRow(tCell, _
                            CStr(arrData(selectedIdx, 1)), _
                            CStr(arrData(selectedIdx, 2)), _
                            CStr(arrData(selectedIdx, 3)), _
                            CStr(arrData(selectedIdx, 9)))
                    Else
                        ' Запасной вариант: только артикул
                        tCell.Value = Split(result, " - ")(0)
                    End If
                End If
            End If

NextCell:
        End If
    Next tCell

CleanUp:
    Application.EnableEvents = True
    Application.ScreenUpdating = True
End Sub


' =============================================================================
' UpdateWVRow — обновляет строку WV 4.0 после выбора артикула
'
' Параметры:
'   tCell   — ячейка столбца B (артикул) в листе WV 4.0
'   article — артикул из БД
'   name    — наименование из БД!C
'   unit    — ед.изм. из БД!D
'   brand   — бренд из БД!J
' =============================================================================
Private Sub UpdateWVRow(tCell As Range, article As String, name As String, unit As String, brand As String)
    Dim r As Long
    r = tCell.Row

    ' Обновляем ячейки строки (события уже отключены в вызывающем коде)
    Me.Cells(r, 1).Value = brand    ' A — Бренд
    tCell.Value           = article  ' B — Артикул
    Me.Cells(r, 3).Value = name     ' C — Наименование
    Me.Cells(r, 4).Value = unit     ' D — Единица измерения
    ' E (Количество) — НЕ ТРОГАЕМ
    Me.Cells(r, 7).Value = ""       ' G — Очищаем константу цены (пересчёт по формуле)
End Sub


' =============================================================================
' Worksheet_SelectionChange — пересчёт ячейки при переходе
' =============================================================================
Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Target.Cells.CountLarge > 1 Then Exit Sub
    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub
    Target.Calculate
End Sub


' =============================================================================
' Worksheet_Activate — полный пересчёт при активации листа
' =============================================================================
Private Sub Worksheet_Activate()
    If Application.CutCopyMode = xlCopy Or Application.CutCopyMode = xlCut Then Exit Sub

    On Error Resume Next
    Application.EnableEvents = False
    Application.ScreenUpdating = False

    Me.Calculate
    Application.CalculateFull

    Application.ScreenUpdating = True
    Application.EnableEvents = True
    On Error GoTo 0
End Sub
