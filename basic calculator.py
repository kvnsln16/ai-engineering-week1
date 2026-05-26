def add(x, y):   # defines function, which is add/addition. (x,y) parameters/placeholders for values
    return x + y # return sends a value back to whom called the function, x+y adds the two parameters, and result will gets returned

def subtract(x, y): # defines function, which is subtract/subtract. (x,y) parameters/placeholders for values
    return x - y    # return sends a value back to whom called the function, x-y subtracts the two parameters, and result will gets returned

def multiply(x, y): # defines function, which is multiply. (x,y) parameters/placeholders for values
    return x * y    # return sends a value back to whom called the function, x*y multiplies the two parameters, and result will gets returned

def divide(x, y):   # defines function, which is divide/division. (x,y) parameters/placeholders for values
    if y == 0:      # if y is equal to zero
        return "Error! Cannot divide by zero."  # then it will get this message
    return x / y    # but if y is not equal to zero the if statement will be ignored and continue to the division/result

print("Welcome to the Basic Calculator!") # displays the text on screen

while True:  # loop, it will check if the statement is True
    print("\nSelect an operation:") # this 6 print calls our menu. \n means new line adds a one space below
    print("1. Add")
    print("2. Subtract")
    print("3. Multiply")
    print("4. Divide")
    print("5. Exit")

    choice = input("Enter your choice (1/2/3/4/5): ") # input from the user

    if choice == "5": # if we choice '5'
        print("Goodbye! Thanks for using the calculator.") # it will print this
        break # exits the while loop on line code 17

    if choice not in ("1", "2", "3", "4"): # if choices from 1-5 are inputted
        print("Invalid input! Please choose 1, 2, 3, 4, or 5.") # shows an error message
        continue # will re-display the menu until it gets valid input

    try: # try block
        num1 = float(input("Enter the first number: ")) #ask the user for inputs , float - converts a text into decimal, num1 - stores the number in variable num1
        num2 = float(input("Enter the second number: ")) 
    except ValueError: # if value error happens in try block, it will jump here instead of crashing
        print("Invalid number! Please enter digits only (e.g., 5 or 3.14).") # show a error message
        continue #skip back to the above loop

    if choice == "1": # check which operation that the users picked
        print(num1, "+", num2, "=", add(num1, num2)) # num1 first number users inputted ...
    elif choice == "2": # else if - if the previous if were false. it will check is choice was not 1
        print(num1, "-", num2, "=", subtract(num1, num2))
    elif choice == "3": # not 2
        print(num1, "*", num2, "=", multiply(num1, num2))
    elif choice == "4": # not 3
        print(num1, "/", num2, "=", divide(num1, num2))