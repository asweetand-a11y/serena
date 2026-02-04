defmodule TestRepo.ModelsTest do
  use ExUnit.Case
  doctest TestRepo.Models

  alias TestRepo.Models.{User, Item, Order, Serializable}

  describe "User" do
    test "creates a new user with default roles" do
      user = User.new("1", "Alice", "alice@example.com")
      
      assert user.id == "1"
      assert user.name == "Alice"
      assert user.email == "alice@example.com"
      assert user.roles == []
    end

    test "creates a user with specified roles" do
      user = User.new("2", "Bob", "bob@example.com", ["admin", "user"])
      
      assert user.roles == ["admin", "user"]
    end

    test "checks if user has role" do
      user = User.new("3", "Charlie", "charlie@example.com", ["admin"])
      
      assert User.has_role?(user, "admin")
      refute User.has_role?(user, "guest")
    end

    test "adds role to user" do
      user = User.new("4", "David", "david@example.com")
      user_with_role = User.add_role(user, "moderator")
      
      assert User.has_role?(user_with_role, "moderator")
      assert length(user_with_role.roles) == 1
    end
  end

  describe "Item" do
    test "creates a new item" do
      item = Item.new("widget1", "Super Widget", 19.99, "electronics")
      
      assert item.id == "widget1"
      assert item.name == "Super Widget"
      assert item.price == 19.99
      assert item.category == "electronics"
    end

    test "formats price for display" do
      item = Item.new("item1", "Test Item", 29.99, "test")
      
      assert Item.display_price(item) == "$29.99"
    end

    test "checks if item is in category" do
      item = Item.new("book1", "Elixir Book", 39.99, "books")
      
      assert Item.in_category?(item, "books")
      refute Item.in_category?(item, "electronics")
    end
  end

  describe "Order" do
    setup do
      user = User.new("customer1", "Customer", "customer@example.com")
      item1 = Item.new("item1", "Item 1", 10.00, "category1")
      item2 = Item.new("item2", "Item 2", 20.00, "category2")
      
      %{user: user, item1: item1, item2: item2}
    end

    test "creates a new order", %{user: user} do
      order = Order.new("order1", user)
      
      assert order.id == "order1"
      assert order.user == user
      assert order.items == []
      assert order.total == 0.0
      assert order.status == :pending
    end

    test "creates order with items", %{user: user, item1: item1, item2: item2} do
      order = Order.new("order2", user, [item1, item2])
      
      assert length(order.items) == 2
      assert order.total == 30.0
    end

    test "adds item to order", %{user: user, item1: item1, item2: item2} do
      order = Order.new("order3", user, [item1])
      order_with_item = Order.add_item(order, item2)
      
      assert length(order_with_item.items) == 2
      assert order_with_item.total == 30.0
    end

    test "updates order status", %{user: user} do
      order = Order.new("order4", user)
      processed_order = Order.update_status(order, :processing)
      
      assert processed_order.status == :processing
    end
  end

  describe "Serializable protocol" do
    test "serializes User" do
      user = User.new("1", "Alice", "alice@example.com", ["admin"])
      serialized = Serializable.to_map(user)
      
      expected = %{
        id: "1",
        name: "Alice",
        email: "alice@example.com",
        roles: ["admin"]
      }
      
      assert serialized == expected
    end

    test "serializes Item" do
      item = Item.new("widget1", "Widget", 19.99, "electronics")
      serialized = Serializable.to_map(item)
      
      expected = %{
        id: "widget1",
        name: "Widget",
        price: 19.99,
        category: "electronics"
      }
      
      assert serialized == expected
    end

    test "serializes Order" do
      user = User.new("1", "Alice", "alice@example.com")
      item = Item.new("widget1", "Widget", 19.99, "electronics")
      order = Order.new("order1", user, [item])
      
      serialized = Serializable.to_map(order)
      
      assert serialized.id == "order1"
      assert serialized.total == 19.99
      assert serialized.status == :pending
      assert is_map(serialized.user)
      assert is_list(serialized.items)
      assert length(serialized.items) == 1
    end
  end

  describe "factory functions" do
    test "creates sample user" do
      user = TestRepo.Models.create_sample_user()
      
      assert user.id == "sample"
      assert user.name == "Sample User"
      assert user.email == "sample@example.com"
      assert "user" in user.roles
    end

    test "creates sample item" do
      item = TestRepo.Models.create_sample_item()
      
      assert item.id == "sample"
      assert item.name == "Sample Item"
      assert item.price == 9.99
      assert item.category == "sample"
    end
  end
end 