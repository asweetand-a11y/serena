defmodule TestRepo.Examples do
  @moduledoc """
  Examples module demonstrating usage of models and services.
  Similar to Python's examples directory, this shows how different modules work together.
  """

  alias TestRepo.Models.{User, Item}
  alias TestRepo.Services.{UserService, ItemService, OrderService}

  defmodule UserManagement do
    @doc """
    Creates a complete user workflow example.
    """
    def run_user_example do
      # Start user service
      {:ok, user_service} = UserService.start_link()

      # Create users
      {:ok, alice} = UserService.create_user(user_service, "1", "Alice", "alice@example.com", ["admin"])
      {:ok, bob} = UserService.create_user(user_service, "2", "Bob", "bob@example.com", ["user"])

      # Get users
      {:ok, retrieved_alice} = UserService.get_user(user_service, "1")

      # List all users
      all_users = UserService.list_users(user_service)

      # Clean up
      GenServer.stop(user_service)

      %{
        created_alice: alice,
        created_bob: bob,
        retrieved_alice: retrieved_alice,
        all_users: all_users
      }
    end

    @doc """
    Demonstrates user role management.
    """
    def manage_user_roles do
      user = User.new("role_user", "Role User", "role@example.com")

      # Add roles
      user_with_admin = User.add_role(user, "admin")
      user_with_multiple = User.add_role(user_with_admin, "moderator")

      # Check roles
      has_admin = User.has_role?(user_with_multiple, "admin")
      has_guest = User.has_role?(user_with_multiple, "guest")

      %{
        original_user: user,
        user_with_roles: user_with_multiple,
        has_admin: has_admin,
        has_guest: has_guest
      }
    end
  end

  defmodule ShoppingExample do
    @doc """
    Creates a complete shopping workflow.
    """
    def run_shopping_example do
      # Create user and items
      user = User.new("customer1", "Customer One", "customer@example.com")
      item1 = Item.new("widget1", "Super Widget", 19.99, "electronics")
      item2 = Item.new("gadget1", "Cool Gadget", 29.99, "electronics")

      # Create order
      order = OrderService.create_order("order1", user)

      # Add items to order
      order_with_item1 = OrderService.add_item_to_order(order, item1)
      order_with_items = OrderService.add_item_to_order(order_with_item1, item2)

      # Process the order
      processed_order = OrderService.process_order(order_with_items)
      completed_order = OrderService.complete_order(processed_order)

      %{
        user: user,
        items: [item1, item2],
        final_order: completed_order,
        total_cost: completed_order.total
      }
    end

    @doc """
    Demonstrates item filtering and searching.
    """
    def item_filtering_example do
      # Start item service
      {:ok, item_service} = ItemService.start_link()

      # Create various items
      ItemService.create_item(item_service, "laptop", "Gaming Laptop", 1299.99, "electronics")
      ItemService.create_item(item_service, "book", "Elixir Guide", 39.99, "books")
      ItemService.create_item(item_service, "phone", "Smartphone", 699.99, "electronics")
      ItemService.create_item(item_service, "novel", "Great Novel", 19.99, "books")

      # Get all items
      all_items = ItemService.list_items(item_service)

      # Filter by category
      electronics = ItemService.list_items(item_service, "electronics")
      books = ItemService.list_items(item_service, "books")

      # Clean up
      Agent.stop(item_service)

      %{
        all_items: all_items,
        electronics: electronics,
        books: books,
        total_items: length(all_items),
        electronics_count: length(electronics),
        books_count: length(books)
      }
    end
  end

  defmodule IntegrationExample do
    @doc """
    Runs a complete e-commerce scenario.
    """
    def run_full_scenario do
      # Setup services
      container = TestRepo.Services.create_service_container()
      TestRepo.Services.setup_sample_data(container)

      # Get sample data
      {:ok, sample_user} = UserService.get_user(container.user_service, TestRepo.Services.sample_user_id())
      {:ok, sample_item} = ItemService.get_item(container.item_service, TestRepo.Services.sample_item_id())

      # Create additional items
      {:ok, premium_item} = ItemService.create_item(
        container.item_service,
        "premium",
        "Premium Product",
        99.99,
        "premium"
      )

      # Create order with multiple items
      order = OrderService.create_order("big_order", sample_user, [sample_item])
      order_with_premium = OrderService.add_item_to_order(order, premium_item)

      # Process through order lifecycle
      processing_order = OrderService.process_order(order_with_premium)
      final_order = OrderService.complete_order(processing_order)

      # Serialize everything for output
      serialized_user = TestRepo.Services.serialize_model(sample_user)
      serialized_order = TestRepo.Services.serialize_model(final_order)

      # Clean up
      GenServer.stop(container.user_service)
      Agent.stop(container.item_service)

      %{
        scenario: "full_ecommerce",
        user: serialized_user,
        order: serialized_order,
        total_revenue: final_order.total,
        items_sold: length(final_order.items)
      }
    end

    @doc """
    Demonstrates error handling scenarios.
    """
    def error_handling_example do
      {:ok, user_service} = UserService.start_link()

      # Try to create duplicate user
      {:ok, _user1} = UserService.create_user(user_service, "dup", "User", "user@example.com")
      duplicate_result = UserService.create_user(user_service, "dup", "Another User", "another@example.com")

      # Try to get non-existent user
      missing_user_result = UserService.get_user(user_service, "nonexistent")

      # Try to delete non-existent user
      delete_result = UserService.delete_user(user_service, "nonexistent")

      GenServer.stop(user_service)

      %{
        duplicate_user_error: duplicate_result,
        missing_user_error: missing_user_result,
        delete_missing_error: delete_result
      }
    end
  end

  @doc """
  Main function to run all examples.
  """
  def run_all_examples do
    %{
      user_management: UserManagement.run_user_example(),
      role_management: UserManagement.manage_user_roles(),
      shopping: ShoppingExample.run_shopping_example(),
      item_filtering: ShoppingExample.item_filtering_example(),
      integration: IntegrationExample.run_full_scenario(),
      error_handling: IntegrationExample.error_handling_example()
    }
  end
end 